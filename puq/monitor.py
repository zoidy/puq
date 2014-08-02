from util import vprint
from logging import info, debug, exception, warning, critical
from puq.options import options
import datetime,sys


class Monitor:
    pass

class QtMonitor(Monitor):
    def __init__(self, host):
        raise Exception, 'PyQt not installed'

class TextMonitor(Monitor):    
    def __init__(self):
        self._time_ref=datetime.datetime.now()
        
    def start_job(self, cmd, currjob,numjobs,dryrun,cpus,cpus_free,topborder=True,bottomborder=True):
        isdryrun=""
        borderstr='================================'
        topborderstr=''
        botborderstr=''
        
        if dryrun:
            isdryrun='--DRY RUN--' 
        jobstr='Job {} of {} {}'.format(currjob,numjobs,isdryrun)
        jobstr+=datetime.datetime.now().ctime()
        cpustr='CPUs provisioned: {}, {} remain free'.format(cpus,cpus_free)
        
        if topborder:
            topborderstr=borderstr +'\n'
        if bottomborder:
            botborderstr=borderstr + '\n'
        printstr=topborderstr + jobstr + '\n' + cpustr + '\n\n' + cmd + '\n' + botborderstr
        
        #if the logging level >=2 then print the full string. else
        #just print a small progress indicator
        if options['verbose']>=2:
            vprint(2,printstr)
        else:
            if (datetime.datetime.now()-self._time_ref).total_seconds()>=0.5:
                #write out the progress every 0.5 seconds
                self._time_ref=datetime.datetime.now()
                if currjob<numjobs:
                    sys.stdout.write('\r{}/{} '.format(currjob,numjobs))                
                    sys.stdout.flush()
            if currjob>=numjobs:
                sys.stdout.write('\r{}/{}\n'.format(currjob,numjobs))
                sys.stdout.flush()
        
        return printstr
