"""
This file is part of PUQ
Copyright (c) 2013 PUQ Authors
See LICENSE file for terms.
"""
import thread,time,datetime,traceback,shlex,sys
from threading import Lock
import multiprocessing
import socket
import os, re, signal, logging
from logging import debug
from monitor import TextMonitor
from jobqueue import JobQueue
from subprocess import Popen, PIPE
import numpy as np
from puq.options import options
from util import vprint
from shutil import rmtree

# fixme: how about supporting Host(name) where name is looked up in a host database?

class Host(object):

    def __init__(self):

        self.run_num = 0

    def reinit(self):
        self.jobs = []

    def add_jobs(self, fname, args):
        self.fname = fname
        
        #a is a generator object. each element is a 
        #realization of the parameters (a list of tuples). On every loop
        #iteration, a new realiztion is returned
        #Called from psweep.run
        for a in args:
            output = '%s_%s' % (fname, self.run_num)
            _dir = self.prog.setup(output)

            if self.prog.paramsByFile:
                cmd = self.prog.cmdByFile(a,_dir)
            else:
                cmd = self.prog.cmd(a) #prog is the testprogram. initialized from sweep.py
            
            self.add_job(cmd, _dir, 0, output)
            self.run_num += 1

    def add_job(self, cmd, dir, cpu, outfile):
        """
        Adds jobs to the queue.

        - *cmd* : Command to execute.
        - *dir* : Directory to run the command in. '' is the default.
        - *cpu* : CPUs to allocate for the job. Don't set this. Only used by scaling method.
        - *outfile* : Output file basename.
        """

        if cpu == 0:
            cpu = self.cpus
        if dir:
            dir = os.path.abspath(dir)
        self.jobs.append({'cmd': cmd,
                          'dir': dir,
                          'cpu': cpu,
                          'outfile': outfile,
                          'status': 0})

    def run(self):
        """
        Run all the jobs in the queue. Returns True on successful completion.
        """
        raise NotImplementedError('This method should have been implemented.')

    # Collect the data from individual stdout and stderr files into
    # the HDF5 file. Remove files when finished.
    def collect(self, hf):
        # Collect results from output files
        debug("Collecting")
        hf.require_group('output')
        run_grp = hf.require_group('output/jobs')

        old_jobs = sorted(map(int, [x for x in hf['/output/jobs'].keys() if x.isdigit()]))

        # find the jobs that are completed and, if the stdout/stderr files are there,
        # move them to hdf5
        finished_jobs = self.status(quiet=True)[0]
        for j in finished_jobs:
            if j in old_jobs:
                continue

            grp = run_grp.require_group(str(j))

            for ext in ['out', 'err']:
                fname = '%s_%s.%s' % (self.fname, j, ext)
                f = open(fname, 'r')
                grp.create_dataset('std%s' % ext, data=f.read())
                f.close()
                if not options['keep']:
                    try:
                        os.remove(fname)
                    except Exception,e:
                        print('Error removing file. {}'.format(str(e)))

            if self.prog.newdir:
                os.chdir('%s_%s' % (self.fname, j))

            for fn in self.prog.outfiles:
                try:
                    f = open(fn, 'r')
                    grp.create_dataset(fn, data=f.read())
                    f.close()
                except:
                    pass

            if self.prog.newdir:
                os.chdir('..')
                # now delete temporary directory
                if not options['keep']:
                    dname = '%s_%s' % (self.fname, j)
                    try:
                        rmtree(dname)
                    except Exception,e:
                        vprint(1,'could not delete directory. {}'.format(dname,str(e)))
        return finished_jobs

    @staticmethod
    def walltime_to_secs(str):
        secs = 0
        a = str.split(':')
        la = len(a)
        if la < 1 or la > 3:
            raise ValueError
        if la == 3:
            secs += 3600 * int(a[-3])
        if la > 1:
            secs += 60 * int(a[-2])
        if la:
            secs += int(a[-1])
        return secs

    @staticmethod
    def secs_to_walltime(secs):
        secs = int(secs)
        hours = secs / 3600
        secs -= (3600 * hours)
        mins = secs / 60
        secs -= (60 * mins)
        return "%s:%02d:%02d" % (hours, mins, secs)

    def cmdline(self, j):
        cmd = '%s > %s.out 2> %s.err' % (j['cmd'], j['outfile'], j['outfile'])
        if j['dir']:
            cmd = 'cd %s;%s' % (j['dir'], cmd)
        return cmd

    def status(self, quiet=0,jobs=None):
        """
        Returns all the jobs in the job queue which have completed.
        """
        if jobs==None:
            jobs=self.jobs
            
        total = len(jobs)
        finished = []
        errors = []
        for num, j in enumerate(jobs):
            if j['status'] == 'F':
                finished.append(num)
            elif j['status'] == 'X':
                finished.append(num)
                errors.append(num)
            elif j['status'] == 0:
                fname = '%s_%s.err' % (self.fname, num)
                try:
                    f = open(fname, 'r')
                except IOError:
                    if hasattr(self, 'prog') and self.prog.newdir:
                        try:
                            fname = os.path.join('%s_%s' % (self.fname, j))
                            f = open(fname, 'r')
                        except:
                            continue
                    else:
                        continue
                for line in f:
                    if line.startswith('HDF5:'):
                        finished.append(num)
                        print 'Marking job %s as Finished' % num
                        j['status'] = 'F'
                        break
                f.close()

        if not quiet:
            print "Finished %s out of %s jobs." % (len(finished), total)

        if errors:
            print "%s jobs had errors." % len(errors)

        return finished, len(finished) == total

class InteractiveHost(Host):
    """
    Create a host object that runs all jobs on the local CPU.

    Args:
      cpus: Number of cpus each process uses. Default=1.
      cpus_per_node: How many cpus to use on each node.
        Default=all cpus.
    """
    def __init__(self, cpus=1, cpus_per_node=0):
        Host.__init__(self)
        if cpus <= 0:
            cpus = 1
        self.cpus = cpus
        if cpus_per_node:
            self.cpus_per_node = cpus_per_node
            if cpus_per_node>multiprocessing.cpu_count():
                print('Warning: the number of parallel jobs requested is greater than the number of'+
                      ' cpus on this machine')
        else:
            self.cpus_per_node = multiprocessing.cpu_count()
        self.hostname = socket.gethostname()
        self.jobs = []
        
        self._lock=Lock()

    # run, monitor and status return
    # True (1) is successful
    # False (0) for errors or unfinished
    def run(self,dryrun=False):
        """ Run all the jobs in the queue """
        self._cpus_free = self.cpus_per_node
        self._running = []
        self._monitor = TextMonitor()
        t_start=datetime.datetime.now()
        print('Start: {}'.format(t_start.ctime()))
        try:
            self._run(dryrun)
            return True
        except KeyboardInterrupt:
            print '***INTERRUPT***\n'
            print "If you wish to resume, use 'puq resume'\n"
            for p, j in self._running:
                try:
                    os.kill(p.pid, 99)
                except Exception,e:
                    print("Error killing pdf {}. {}".format(p.pid,str(e)))
                j['status'] = 0
            return False
        finally:
            t_end=datetime.datetime.now()
            print('End: {}\tElapsed: {}'.format(t_end.ctime(),t_end-t_start))
         

    def _run(self,dryrun=False):

        # fix for some broken saved jobs
        for i, j in enumerate(self.jobs):
            if type(j) == str or type(j) == np.string_:
                self.jobs[i] = eval(j)

        errors = len([j for j in self.jobs if j['status'] == 'X'])
        if errors:
            print "Previous run had %d errors. Retrying." % errors

        count=1
        for j in self.jobs:
            if j['status'] == 0 or j['status'] == 'X':
                cmd = j['cmd']
                cpus = min(j['cpu'], self.cpus)
                
                if cpus > self._cpus_free:
                    self.wait(cpus)
                self._cpus_free -= cpus
                sout = open(j['outfile']+'.out', 'w')
                serr = open(j['outfile']+'.err', 'w')              
                if j['dir']:
                    cmd = 'cd %s && %s' % (j['dir'], cmd) #UNIX ; to &&
                
                jobstr,cpustr=self._monitor.start_job(cmd,count,len(self.jobs),dryrun,cpus,
                                                      self._cpus_free,True,False,True)
                
                if dryrun:
                    cmd="echo HDF5:{{'name': 'DRY_RUN', 'value': {}, 'desc': '--DRY RUN--'}}:5FDH".format(count)
                
                #include echoing commands so that the info is saved in the hdf5 file.
                #escape the ampersands for windows (UNIX is different)
                cmd2=cmd.replace('&','^&')
                cmd='echo {} && echo {} && echo {} && {}'.format(jobstr,cpustr,cmd2,cmd)
                                
                # We are going to wait for each process, so we must keep the Popen object
                # around, otherwise it will quietly wait for the process and exit,
                # leaving our wait function waiting for nonexistent processes.
                t_start=time.clock()
                p = Popen(cmd , shell=True, stdout=sout, stderr=serr)
                
                vprint(2,'pid: {}\n{}\n'.format(p.pid,'================================'))
                count+=1
                
                thread.start_new_thread(self.process_waiter,(p,t_start,))
                
                j['status'] = 'R' 
                self._running.append((p, j))
                                
        self.wait(0)
        sys.stdout.flush()
        sys.stderr.flush()

    def process_waiter(self,popen,t_start=None):
        #http://stackoverflow.com/questions/100624
        
        if t_start==None:
            t_start=time.clock()
            
        t_end=t_start
        try: 
            popen.wait()
            
            #wait for the lock once the process finishes
            self._lock.acquire()
        finally: 
            t_end=time.clock()
            w=[popen.pid,popen.returncode]
            found=False
            for p, j in self._running:
                if p.pid == w[0]:
                    found=True
                    self._running.remove((p, j))
                    if w[1]>0:
                        self.handle_error(w[1], j,p.pid)
                        j['status'] = 'X'
                    else:
                        j['status'] = 'F'
                    self._cpus_free += j['cpu']
                    
                    #we're done messing with the shared vars. release the lock.
                    self._lock.release()
                    
                    #substitute the time command from Host __init__ and add a timestamp to .out file
                    f=open(j['outfile']+'.err','a')
                    f.write("HDF5:{{'name':'time','value':{},'desc':''}}:5FDH".format(
                        t_end-t_start))
                    f.close()
                    
                    f=open(j['outfile']+'.out','a')
                    f.write(datetime.datetime.now().ctime())
                    f.close()
                    
                    break
            
            if not found:
                self._lock.release()
        
    def handle_error(self, stat, j,pid=-1):
        str=60*'x' + '\n'
        str+="ERROR (pid {}): {} returned {}\n".format(pid,j['cmd'], stat)
        try:
            for line in open(j['outfile']+'.err', 'r'):
                if not re.match("HDF5:{'name':'time','value':([0-9.]+)", line):
                    str+=line
        except:
            pass
        str+="Stdout is in {}.out and stderr is in {}.err.\n".format(j['outfile'], j['outfile'])
        str+=60*'x' + '\n'
        print(str)
    
    def wait(self,cpus):
        while len(self._running):
            time.sleep(0.1)
            if cpus and self._cpus_free >= cpus:
                return

class InteractiveHostMP(Host):
    """
    This is a multiprocessing version of InteractiveHost.  It can only be used when using
    a python function as the test program. See example 4 of :class:`TestProgram`.
    
    Unlike InteractiveHost which
    relies on launching separate python instances for each run, this class executes python
    functions directly using the multiprocessing module and a process pool. This reduces
    overhead significantly.
    
    - *cpus*: The number of cpus to assign to a single job.
    - *cpus_per_node*: The total number of cpus to use. If *cpus* = 1, then this parameter
      is the number of concurrent jobs which will run on the machine.
    - *proc_pool*: An externally created multiprocessing.Pool to use as the process pool. If
      not specified, a new pool will be created.
    """
    
    _numinstances=0
    
    _cpus=-1
    _cpus_free=-1
    _cpus_per_node=-1
    _running={}
    _run_num=-1
    _jobs={}
    
    _lock=Lock()
    
    def __init__(self,cpus=1,cpus_per_node=0,proc_pool=None):
        #only allow a single instance of InteractiveHostMP if there are jobs running.
        if InteractiveHostMP._numinstances>=1 and len(InteractiveHostMP._running)>0:
            raise Exception('Only one instance of InteractiveHostMP is allowed')
        InteractiveHostMP._numinstances+=1            
            
        if cpus <= 0:
            cpus = 1
        InteractiveHostMP._cpus = cpus
        if cpus_per_node:
            InteractiveHostMP._cpus_per_node=cpus_per_node
            if cpus_per_node>multiprocessing.cpu_count():
                print('Warning: the number of parallel jobs requested is greater than the number of'+
                      ' cpus on this machine')
        else:
            InteractiveHostMP._cpus_per_node = multiprocessing.cpu_count()
        self.hostname = socket.gethostname()
        
        InteractiveHostMP._run_num=0
        InteractiveHostMP._jobs={}
        InteractiveHostMP._lock=Lock()
        self._testProgramFunc=None
        self._pool=proc_pool
        
        #for pickling purposes
        self.jobs=InteractiveHostMP._jobs
        
        #don't use inheritance since we only want some methods
        self._host=Host()
        
    def close(self):
        #don't use __del__. It doesn't work reliably
        if len(InteractiveHostMP._running)>0:
            raise Exception('Jobs are still running. Cannot close now')
        else:
            InteractiveHostMP._numinstances-=1
        
    def reinit(self):
        InteractiveHostMP._jobs = {}

    def add_jobs(self, fname, args):
        #fname comes from sweeep.run
        self.fname = fname
        
        #self.prog is set in sweep.__init__
        if self.prog.func==None:
            raise Exception('for InteractiveHostMP, TestProgram.func must be defined')
            
        self._testProgramFunc=self.prog.func
        
        #a is a generator object. each element is a 
        #realization of the parameters (a list of tuples). On every loop
        #iteration, a new realiztion is returned
        #Called from psweep.run
        for a in args:
            output = '%s_%s' % (fname, InteractiveHostMP._run_num)
            _dir = self.prog.setup(output)

            if self.prog.paramsByFile:
                cmd = self.prog.cmdByFile(a,_dir)
            else:
                cmd = self.prog.cmd(a) #prog is the testprogram. initialized from sweep.py
            
            self.add_job(self._testProgramFunc, _dir, 0, output,cmd)
            
    def add_job(self, func, dir, cpu, outfile,funcparams):
        """
        Adds jobs to the queue.

        - *func* : python function to execute.
        - *dir* : Directory to run the command in. '' is the default.
        - *cpu* : CPUs to allocate for the job. Don't set this. Only used by scaling method.
        - *outfile* : Output file basename.
        - *paramdict*: list of parameters for *func* (in optparse format)
        
        """
        if func==None:
            raise Exception('add_job: func must be defined')
        if self._testProgramFunc!=None and func!=self._testProgramFunc:
            raise Exception('add_job: func must be the same for all jobs')
        self._testProgramFunc=func
        
        if cpu == 0:
            cpu = InteractiveHostMP._cpus
        if dir:
            dir = os.path.abspath(dir)
        InteractiveHostMP._jobs[InteractiveHostMP._run_num]={ 'dir': dir,
                                                              'cpu': cpu,
                                                              'outfile': outfile,
                                                              'status': 0,
                                                              'args':funcparams}
        InteractiveHostMP._run_num += 1
        
    def collect(self,hf):
        #should be ok to use the version in Host
        return Host.collect(self,hf)
        
    def status(self,quiet=0):
        return Host.status(self,quiet,list(InteractiveHostMP._jobs.itervalues()))
        
    def run(self,dryrun=False):
        if len(InteractiveHostMP._jobs)==0:
            print('No jobs to run')
            return False
            
        InteractiveHostMP._cpus_free = InteractiveHostMP._cpus_per_node
        InteractiveHostMP._running = {}
        self._monitor = TextMonitor()
        
        if self._pool==None:
            pool=multiprocessing.Pool(processes=InteractiveHostMP._cpus_per_node)
        else:
            pool=self._pool
        
        t_start=datetime.datetime.now()
        print('Start: {}'.format(t_start.ctime()))
        try:
            self._run(pool,dryrun)
            return True
        except KeyboardInterrupt:
            pool.terminate()
            pool.join()
            
            print '***INTERRUPT***\n'
            print "If you wish to resume, use 'puq resume'\n"
            for jobnum in InteractiveHostMP._running:
                j=InteractiveHostMP._jobs[jobnum]
                j['status'] = 0
            return False
        finally:
            if self._pool==None:
                pool.close()
                pool.join()
            t_end=datetime.datetime.now()
            print('End: {}\tElapsed: {}'.format(t_end.ctime(),t_end-t_start))
            
    def _run(self,pool,dryrun=False):
        # fix for some broken saved jobs
        for jobnum,jobdata in InteractiveHostMP._jobs.iteritems():
            if type(jobdata) == str or type(jobdata) == np.string_:
                InteractiveHostMP._jobs[jobnum]=eval(jobdata)

        errors = len([j for j in InteractiveHostMP._jobs.itervalues() if j['status'] == 'X'])
        if errors:
            print "Previous run had %d errors. Retrying." % errors

        cwd=os.getcwd()
        
        for jobnum,j in InteractiveHostMP._jobs.iteritems():
            if j['status'] == 0 or j['status'] == 'X':
                cpus = min(j['cpu'], InteractiveHostMP._cpus)
                
                if cpus > InteractiveHostMP._cpus_free:
                    self.wait(cpus)
                
                t_start=time.clock()
                job_info_args={'jobnum':jobnum, 'start_time':t_start}
                job_other_args=shlex.split(j['args']) #j['args'] should be a string
                
                funcstr=str(self._testProgramFunc) + '\n'
                funcstr+='Parameters: args={}, jobinfo={}\n'.format(job_other_args,job_info_args)
                funcstr+='stdout: {} stderr:{}'.format(j['outfile']+'.out',j['outfile']+'.err')
                
                InteractiveHostMP._lock.acquire()
                InteractiveHostMP._cpus_free -= cpus
                j['status']='R'
                InteractiveHostMP._running[jobnum]=None
                s=self._monitor.start_job(funcstr,jobnum+1,len(InteractiveHostMP._jobs),dryrun,
                                          cpus,InteractiveHostMP._cpus_free)
                InteractiveHostMP._lock.release()
                
                self._write_stdio(jobnum,stdout_msg=s)
                
                if dryrun:
                    #write the output and timing info immediately
                    InteractiveHostMP._write_stdio(jobnum,
                        stdout_msg="HDF5:{{'name': 'DRY_RUN', 'value': {}, 'desc': '--DRY RUN--'}}:5FDH".format(0),
                        stderr_msg="HDF5:{{'name':'time','value':{},'desc':''}}:5FDH".format(time.clock()-t_start),
                        mode='a')
                    
                    InteractiveHostMP._lock.acquire()
                    j['status']='F'
                    InteractiveHostMP._lock.release()
                else:                    
                    #start an async job. When finished successfully (i.e., without exceptions),
                    #the callback will be called.
                    #
                    #_testProgramFunc must not be a method of a class. It must be a standalone
                    #function in a module.
                    async_result=pool.apply_async(_InteractiveHostMP_run_testProgramFunc,
                                                  kwds={'args':job_other_args,
                                                        'jobinfo':job_info_args,
                                                        'func':self._testProgramFunc,
                                                        'stdout_file':j['outfile']+'.out',
                                                        'stderr_file':j['outfile']+'.err',
                                                        'workingdir':cwd,
                                                        'jobworkingdir':j['dir']},
                                                  callback=InteractiveHostMP._job_finished_callback)
                                                  
                    #if there is an exception, the callback WON'T be called. Therefore we need to
                    #poll the job to see if it finished successfully. Use a separate thread.
                    #If the call did in fact complete successfully, the waiter will complete
                    #without doing anything.
                    thread.start_new_thread(self._process_waiter,(jobnum,async_result,t_start,))

                #end if dryrun    
            #end if j['status'] == 0 or j['status'] == 'X':
                                                                    
        sys.stdout.flush()
        if self._pool==None:
            #if the pool has NOT been externally created,
            #wait for all jobs in the pool to finish
            #print('waiting on pool close and join')
            pool.close()
            pool.join()
            #if the pool has been externally created, cant wait using the above
            #method since the method requires closing the pool. Instead, we must
            #rely on the self.wait(0) call below

        #wait for callbacks and error handlers to finish before exiting
        #1 sec should be enough of a wait since each process_waiter only
        #sleeps for 0.1 sec
        #print('waiting on wait function')
        sys.stdout.flush()
        time.sleep(0.6)
        
        #really make sure that all callbacks and waiters are finished
        #code wont proceed past this point untill the list of running jobs
        #is empty.
        self.wait(0)        

    
    @staticmethod
    def _job_finished_callback(args):
        #args is the return value of self._testProgramFunc. self._testProgramFunc must
        #return the 'jobinfo' argument which was passed to in in apply_async
        
        #The callbacks are handled in the main process, but they're run in their own separate thread.
        #See http://stackoverflow.com/questions/24770934
        s=''
        
        #if this callback is called, the async function completed with no exceptions
        jobnum=args['jobnum']
        t_start=args['start_time']
        # s+='Job {} finished successfully. waited {} sec. Waiting for lock...\n'.format(jobnum,
                                # time.clock()-t_start)
        # print(s)
        # sys.stdout.flush()
        # s=''
        
        t_start_lock=time.clock()
        InteractiveHostMP._lock.acquire()
        # s+='Job {} Lock acquired, waited {} sec\n'.format(jobnum,time.clock()-t_start_lock)
        # print(s)
        # sys.stdout.flush()
        # s=''
        
        try:            
            j=InteractiveHostMP._jobs[jobnum]
            t_end=time.clock()
            now=datetime.datetime.now().ctime()
            
            err=''
            try:
                InteractiveHostMP._write_stdio(jobnum,stdout_msg=now,
                    stderr_msg="HDF5:{{'name':'time','value':{},'desc':''}}:5FDH".format(t_end-t_start),
                    mode='a')
            except Exception,e:
                err+='ERROR: could not write time data to output file.\n{}'.format(traceback.format_exc())
            
            try:
                InteractiveHostMP._cpus_free+=j['cpu']                
                del InteractiveHostMP._running[jobnum]
            except Exception,e:
                err+='ERROR: could not finish updating job queue.\n{}'.format(traceback.format_exc())         

            #only write if there was an error. Else the output gets too much
            if err!='':
                j['status']='X'
                s+='............................................................\n'
                s+='Job {} of {} completed but there was an error afterwards, {}.\n'.format(jobnum+1,
                            len(InteractiveHostMP._jobs),now)
                s+=err
                s+='Elapsed: {} sec\n'.format(t_end-t_start)
                s+='............................................................\n'
                
                InteractiveHostMP._write_stdio(jobnum,stderr_msg=s,mode='a')
                
                print(s)
            else:
                j['status']='F'
        finally:
            InteractiveHostMP._lock.release()
            #print('Job {} lock released.'.format(jobnum))
        
    def _process_waiter(self,jobnum,async_result,t_start):
        #if a process is stuck, continue as if there was an error. Note that the 
        #process is not killed. If the process completes after the time out, 
        #_job_finished_callback is still called but it will silently fail since
        #the job is no longer in the queue.
        timeout=1800 #each process will only be allowed to run for 1800sec (0.5 hr)
        timeout_elapsed=False
        timeout_start=time.clock()
        while not async_result.ready():
            time.sleep(0.1)
            if time.clock()-timeout_start>=timeout:
                timeout_elapsed=True
                break

        #job has exited. was it successful? If so, then _jobfinished_callback ran.
        #If not, then it wasn't called and we need to handle the error here
        err=''
        if timeout_elapsed or not async_result.successful():
            try:
                #s='Job {} completed with ERRORS. waited {} sec.\n'.format(jobnum,
                #                    time.clock()-t_start)
                if not timeout_elapsed:
                    async_result.get()
                else:
                    raise Exception('Job {} timed out after {} sec'.format(jobnum,timeout))
            except Exception:
                #note this won't be the full traceback unfortunately...
                #See http://stackoverflow.com/a/8708806
                err=traceback.format_exc()
            finally:
                InteractiveHostMP._lock.acquire()
                
                j=InteractiveHostMP._jobs[jobnum]
                t_end=time.clock()
                now=datetime.datetime.now().ctime()
            
                try:
                    InteractiveHostMP._write_stdio(jobnum,
                        stdout_msg=now,
                        stderr_msg="HDF5:{{'name':'time','value':{},'desc':''}}:5FDH".format(t_end-t_start),
                        mode='a')
                except Exception,e:
                    err+='ERROR: could not write time data to output file.\n{}'.format(traceback.format_exc())
                                
                InteractiveHostMP._cpus_free+=j['cpu']
                j['status']='X'
                del InteractiveHostMP._running[jobnum]
                
                #s+='job {} total elapsed: {}\n'.format(jobnum,time.clock()-t_start)
                self.handle_error(err,j,jobnum,t_start)
                
                InteractiveHostMP._lock.release()
        else:
            #job finished successfully. Do nothing here.
            #print('job {} was successful'.format(jobnum))
            pass
    
    def handle_error(self,err,j,jobnum,t_start):
        s='\n' + 'x'*60 +'\n'
        s+='Job {} of {} completed with ERRORS, {}.\n'.format(jobnum+1,len(InteractiveHostMP._jobs),
                    datetime.datetime.now().ctime())
        s+='Elapsed: {} sec\n'.format(time.clock()-t_start)
        s+=err
        try:
            for line in open(j['outfile']+'.err', 'r'):
                if not re.match("HDF5:{'name':'time','value':([0-9.]+)", line):
                    s+=line
        except:
            pass
        s+='\n' + 'x'*60 + '\n'
        
        InteractiveHostMP._write_stdio(jobnum,stderr_msg=s,mode='a')

        print(s)
        
    @staticmethod
    def _write_stdio(jobnum,stdout_msg=None,stderr_msg=None,mode='w'):
        j=InteractiveHostMP._jobs[jobnum]
        
        sout_name=j['outfile']+'.out'
        serr_name=j['outfile']+'.err'
        
        if stdout_msg!=None:
            sout = open(sout_name, mode)
            sout.write(stdout_msg)
            sout.close()
        if stderr_msg!=None:
            serr = open(serr_name, mode)
            serr.write(stderr_msg)
            serr.close()
            
    
    def wait(self,cpus):
        count=0
        while len(InteractiveHostMP._running):
            time.sleep(0.1)
            if cpus and InteractiveHostMP._cpus_free >= cpus:
                return
            #this if tests for a race condition at the end of the run. 
            #Can comment out if condition is not observed after a while
            # if not cpus:
                # print(len(InteractiveHostMP._running),
                    # [j for j in InteractiveHostMP._jobs.keys() if InteractiveHostMP._jobs[j]['status']=='R'],
                    # InteractiveHostMP._cpus_free,cpus)
                # if count>10:                    
                    # raise Exception("DEBUG. You shouldn't see this error.")
                # count+=1
                
def _InteractiveHostMP_run_testProgramFunc(func,jobinfo,args,stdout_file=None,stderr_file=None,
                                           workingdir=None,jobworkingdir=None):
    """
    Used by InteractiveHostMP._run to call the test function while redirecting IO.
    
    All Python IO from func will be redirected to the indicated files. Note that
    to capture IO from non-python programs, func will have to capture that IO and
    output it to the redirected stdout and stderr using print statements or
    by redirecting the streams when using Popen.
    
    This function must exist outside of a class so that is is callable by 
    pool.apply_async. This function runs in a separate process.
    """
    if workingdir!=jobworkingdir and (workingdir==None or jobworkingdir==None):
        raise Exception('workingdir and jobsworkingdir must be specified together')
        
    #workingdir is where puq expects the stdout and stderr files to be
    try:
        if workingdir!=None and workingdir!='':
            os.chdir(workingdir)
    except Exception,e:
        raise Exception('Could not change working directory to {}'.format(wdir))
    
    try:
        if type(stdout_file) is str and stdout_file!=stderr_file:
            sys.stdout=open(stdout_file,'a')
    except Exception,e:
        raise Exception('Could not redirect stdout to "{}". {}'.format(stderr_file,str(e)))
        
    try:
        if type(stderr_file) is str and stderr_file!=stdout_file:
            sys.stderr=open(stderr_file,'a')
    except Exception,e:
        raise Exception('Could not redirect stderr to "{}". {}'.format(stdout_file,str(e)))
        
    try:
        if type(stdout_file) is str and type(stderr_file) is str and stderr_file==stdout_file:
            f=open(stdout_file,'a')
            sys.stdout=f
            sys.stderr=f
    except Exception,e:
        raise Exception('Could not redirect stdout and stderr to "{}". {}'.format(stdout_file,str(e)))
    
    #change to the job working directory after stdout and stderr have been redirected
    try:
        if jobworkingdir!=None and jobworkingdir!='':
            os.chdir(jobworkingdir)
    except Exception,e:
        raise Exception('Could not change job working directory to {}'.format(wdir))
    
    try:
        r=func(**{'jobinfo':jobinfo,'args':args})
        return r
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        if stdout_file!=None:
            sys.stdout.close()
        if stderr_file!=None:
            sys.stderr.close()
        os.chdir(workingdir)

        
        
class TestHost(Host):        
    def __init__(self, cpus=0, cpus_per_node=0, walltime='1:00:00', pack=1):
        raise Exception("This host is not supported")
        
        Host.__init__(self)
        if cpus <= 0:
            print "You must specify cpus when creating a PBSHost object."
            raise ValueError
        if cpus_per_node <= 0:
            print "You must specify cpus_per_node when creating a PBSHost object."
            raise ValueError
        self.cpus = cpus
        self.cpus_per_node = cpus_per_node
        self.walltime = walltime
        self.jobs = []
        self.wqueue = []
        self.wlist = []
        self.pack = pack
        self.scaling = False
        self.jnum = 0

    @staticmethod
    def job_status(j):
        j['status'] = 'F'

    def add_job(self, cmd, dir, cpu, outfile):
        if cpu == 0:
            cpu = self.cpus
        else:
            self.scaling = True
        num = len(self.jobs)
        self.jobs.append({'num': num,
                          'cmd': cmd,
                          'cpu': cpu,
                          'dir': dir,
                          'outfile': outfile,
                          'status': 0,
                          'job': '',
                          'secs': 0,
                          'walltime': self.walltime})

    def check(self, pbsjob):
        """
        Returns the status of PBS jobs.
        'F' = Finished
        'Q' = Queued
        'R' = Running
        'U' = Unknown
        """
        pbsjob['job_state'] = 'F'

    def submit(self, cmd, joblist, walltime):
        global output
        cpu = joblist[0]['cpu']
        cpn = self.cpus_per_node
        nodes = int((cpu + cpn - 1) / cpn)
        walltime = self.secs_to_walltime(walltime)
        output.append({'job': self.jnum,
                       'cpu': cpu,
                       'cpu': cpn,
                       'nodes': nodes,
                       'walltime': walltime,
                       'cmd': cmd})

        job = joblist[0]['num']+100
        for j in joblist:
            j['job'] = job
            j['status'] = 'Q'
        d = {'jnum': self.jnum, 'joblist': joblist, 'jobid': job}
        self.jnum += 1
        return d

    def run(self):
        jobq = JobQueue(self, limit=10, polltime=1)
        for j in self.jobs:
            if j['status'] == 0 or j['status'] == 'Q':
                debug("adding job %s" % j['num'])
                jobq.add(j)
        jobq.start()
        return jobq.join() == []


def testHost0():
    global output
    output = []
    th = TestHost(cpus=1, cpus_per_node=1, walltime='10:00', pack=1)
    th.add_job('foobar', '', 0, 'xxx')
    th.run()
    assert len(output) == 1
    assert output[0]['walltime'] == '0:10:00'

def testHost1():
    global output
    output = []
    th = TestHost(cpus=1, cpus_per_node=1, walltime='10:00', pack=1)
    th.add_job('foobar -1', '', 0, 'xxx')
    th.add_job('foobar -2', '', 0, 'xxx')
    th.add_job('foobar -3', '', 0, 'xxx')
    th.add_job('foobar -4', '', 0, 'xxx')
    th.run()
    assert len(output) == 4
    assert output[0]['walltime'] == '0:10:00'

def testHost2():
    global output
    output = []
    th = TestHost(cpus=1, cpus_per_node=1, walltime='10:00', pack=4)
    th.add_job('foobar -1', '', 0, 'xxx')
    th.add_job('foobar -2', '', 0, 'xxx')
    th.add_job('foobar -3', '', 0, 'xxx')
    th.add_job('foobar -4', '', 0, 'xxx')
    th.run()
    assert len(output) == 1
    assert output[0]['walltime'] == '0:40:00'

def testHost3():
    global output
    output = []
    th = TestHost(cpus=2, cpus_per_node=4, walltime='10:00', pack=1)
    for i in range(11):
        th.add_job('foobar', '', 0, 'xxx')
    th.run()
    assert len(output) == 6
    assert output[0]['walltime'] == '0:10:00'

def testHost4():
    global output
    output = []
    th = TestHost(cpus=2, cpus_per_node=4, walltime='10:00', pack=3)
    for i in range(11):
        th.add_job('foobar', '', 0, 'xxx')
    th.run()
    assert len(output) == 2
    assert output[0]['walltime'] == '0:30:00'

def testHost5():
    global output
    output = []
    th = TestHost(cpus=22, cpus_per_node=4, walltime='10:00', pack=1)
    th.add_job('foobar', '', 0, 'xxx')
    th.add_job('foobar', '', 0, 'xxx')
    th.run()
    assert len(output) == 2
    assert output[0]['walltime'] == '0:10:00'
    assert output[1]['walltime'] == '0:10:00'
    assert output[0]['nodes'] == 6
    assert output[1]['nodes'] == 6
    assert output[0]['cpu'] == 4
    assert output[1]['cpu'] == 4

def testHostMultiRun():
    global output
    output = []
    th = TestHost(cpus=1, cpus_per_node=1, walltime='10:00', pack=1)
    th.add_job('foobar -1', '', 0, 'xxx')
    th.add_job('foobar -2', '', 0, 'xxx')
    th.add_job('foobar -3', '', 0, 'xxx')
    th.add_job('foobar -4', '', 0, 'xxx')
    th.run()
    print '-'*80
    th.add_job('foobar -5', '', 0, 'xxx')
    th.add_job('foobar -6', '', 0, 'xxx')
    th.add_job('foobar -7', '', 0, 'xxx')
    th.add_job('foobar -8', '', 0, 'xxx')
    th.run()
    print output

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    #testHost0()
    #testHost1()
    #testHost2()
    #testHost3()
    #testHost4()
    #testHost5()
    testHostMultiRun()
    print 'OK'
