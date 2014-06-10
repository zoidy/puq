"""
This file is part of PUQ
Copyright (c) 2013 PUQ Authors
See LICENSE file for terms.
"""
import thread,time #FR
import socket
import os, re, signal, logging
from logging import debug
from monitor import TextMonitor
from jobqueue import JobQueue
from subprocess import Popen, PIPE
import numpy as np
from puq.options import options
from shutil import rmtree

# fixme: how about supporting Host(name) where name is looked up in a host database?

class Host(object):

    def __init__(self):

        # Need to find GNU time.  If /usr/bin/time is not GNU time
        # then PUQ expects it to be in the path and called 'gtime'
        tstr = 'gtime'
        try:
            ver = Popen("/usr/bin/time --version", shell=True, stderr=PIPE).stderr.read()
            if ver.startswith("GNU"):
                tstr = '/usr/bin/time'
        except:
            pass

        #self.timestr = tstr + " -f \"HDF5:{'name':'time','value':%e,'desc':''}:5FDH\""
        self.timestr="" #FR
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
                cmd=self.prog.cmdByFile(a,_dir)
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
                    os.remove(fname)

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
                    except:
                        pass
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
        cmd = '%s %s > %s.out 2> %s.err' % (self.timestr, j['cmd'], j['outfile'], j['outfile'])
        if j['dir']:
            cmd = 'cd %s;%s' % (j['dir'], cmd)
        return cmd

    def status(self, quiet=0):
        """
        Returns all the jobs in the job queue which have completed.
        """
        total = len(self.jobs)
        finished = []
        errors = []
        for num, j in enumerate(self.jobs):
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
        from multiprocessing import cpu_count
        if cpus <= 0:
            cpus = 1
        self.cpus = cpus
        if cpus_per_node:
            self.cpus_per_node = cpus_per_node
        else:
            self.cpus_per_node = cpu_count()
        self.hostname = socket.gethostname()
        self.jobs = []

    # run, monitor and status return
    # True (1) is successful
    # False (0) for errors or unfinished
    def run(self,dryrun=False):
        """ Run all the jobs in the queue """
        self._cpus_free = self.cpus_per_node
        self._running = []
        self._monitor = TextMonitor()
        try:
            self._run(dryrun)
            return True
        except KeyboardInterrupt:
            print '***INTERRUPT***\n'
            print "If you wish to resume, use 'puq resume'\n"
            for p, j in self._running:
                os.kill(p.pid, signal.SIGKILL)
                j['status'] = 0
            return False

    def _run(self,dryrun=False):

        # fix for some broken saved jobs
        for i, j in enumerate(self.jobs):
            if type(j) == str or type(j) == np.string_:
                self.jobs[i] = eval(j)

        errors = len([j for j in self.jobs if j['status'] == 'X'])
        if errors:
            print "Previous run had %d errors. Retrying." % errors

        count=1 #FR
        for j in self.jobs:
            if j['status'] == 0 or j['status'] == 'X':
                cmd = j['cmd']
                cpus = min(j['cpu'], self.cpus)
                
                if cpus > self._cpus_free:
                    self.wait(cpus)
                self._cpus_free -= cpus
                sout = open(j['outfile']+'.out', 'w')
                serr = open(j['outfile']+'.err', 'w')
                cmd = self.timestr + ' ' + cmd
                if j['dir']:
                    cmd = 'cd %s && %s' % (j['dir'], cmd) #FR changed ; to &&
                
                
                #FR                
                isdryrun=""
                if dryrun:
                    isdryrun='--DRY RUN--' 
                jobstr='Job {} of {} {}'.format(count,len(self.jobs),isdryrun)
                cpustr='CPUs requested: {} available: {}'.format(cpus,self._cpus_free)
                borderstr='================================'
                print(borderstr +'\n' + jobstr + '\n' + cpustr + '\n\n' + cmd +'\n')                
                
                if dryrun:
                    cmd="echo HDF5:{{'name': 'DRY_RUN', 'value': {}, 'desc': '--DRY RUN--'}}:5FDH".format(count)
                
                #include echoing commands so that the info is saved in the hdf5 file.
                #escape the ampersands for windows
                cmd2=cmd.replace('&','^&')
                cmd='echo {} && echo {} && echo {} && {}'.format(jobstr,cpustr,cmd2,cmd)
                                
                # We are going to wait for each process, so we must keep the Popen object
                # around, otherwise it will quietly wait for the process and exit,
                # leaving our wait function waiting for nonexistent processes.               
                p = Popen(cmd , shell=True, stdout=sout, stderr=serr)
                
                #FR
                print('Started process {}\n{}\n'.format(p.pid,borderstr))                
                count+=1
                
                #FR
                thread.start_new_thread(self.process_waiter,(p,))
                
                j['status'] = 'R' 
                self._running.append((p, j))
                self._monitor.start_job(j['cmd'], p.pid)
                                
        self.wait(0)


    #FR
    def process_waiter(self,popen):
        #http://stackoverflow.com/questions/100624
        t_start=time.clock()
        t_end=t_start
        try: 
            popen.wait()
            t_end=time.clock()
        finally: 
            w=[popen.pid,popen.returncode]
            for p, j in self._running:
                if p.pid == w[0]:
                    self._running.remove((p, j))
                    if w[1]>0:
                        self.handle_error(w[1], j,p.pid)
                        j['status'] = 'X'
                    else:
                        j['status'] = 'F'
                    self._cpus_free += j['cpu']
                    
                    #substitute the time command in Host __init__
                    f=open(j['outfile']+'.err','a')
                    f.write("HDF5:{{'name':'time','value':{},'desc':''}}:5FDH".format(
                        t_end-t_start))
                    f.close()
                    
                    
                    break
        
    def handle_error(self, stat, j,pid=-1):
        #stat = os.WEXITSTATUS(stat) #FR
        str=40*'*' + '\n'
        str+="ERROR (pid {}): {} returned {}\n".format(pid,j['cmd'], stat)
        try:
            for line in open(j['outfile']+'.err', 'r'):
                if not re.match("HDF5:{'name':'time','value':([0-9.]+)", line):
                    str+=line
        except:
            pass
        str+="Stdout is in {}.out and stderr is in {}.err.\n".format(j['outfile'], j['outfile'])
        str+=40*'*' + '\n'
        print(str)
    
    #FR
    def wait(self,cpus):
        while len(self._running):
            time.sleep(0.1)
            if cpus and self._cpus_free >= cpus:
                return

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
