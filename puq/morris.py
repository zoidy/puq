"""
Morris Method of Sensitivity Analysis

Fernando Rios 2014
"""

import numpy as np
import random
from puq.util import process_data
from puq.psweep import PSweep
from logging import info, debug, exception, warning, critical
from puq.response import SampledFunc
from puq.jpickle import pickle,unpickle
from puq.pdf import UniformPDF, ExperimentalPDF
import SALib.sample as SAs
import SALib.analyze as SAa
import os
import filecmp

class Morris(PSweep):
    def __init__(self, params, numtrajectories,levels,gridjump, response=False, iteration_cb=None):
        if response:
            print('Morris method does not support creating response surfaces')
            raise ValueError
        
        #output of puq run is 1 elementary effect for each parameter per trajectory.
        #Therefore, each parameter will have *numtrajectories* elementary effects.
        
        PSweep.__init__(self, iteration_cb)
        self.params = params
        num = int(numtrajectories)
        self.num = num*(len(params)+1) #total number of model runs for morris
        self.response = response
        self._start_at = 0
        self.levels=levels
        self.gridjump=gridjump
        
        self._hf=None

        self._salib_paramFile='==SALib_morris_params==.txt'
        self._salib_realizationsFile='==SALib_morris_realizations==.txt'
        self._salib_realizationsFile_verify='==0SALib_morris_realizations==.txt'
        self._salib_analysisFile='==SALib_morris_outputs==.txt'
            
        #generate morris samples N(D+1) x D numpy array. Rows are realizations, columns are params
        #Each column is independent in the range [0,1]
        #TODO: allow for correlation
        self._samples=SAs.morris_oat.sample(N=num,D=len(params),num_levels=levels,grid_jump=gridjump)
        
        #puq will evaluate the output by picking a sample from each parameter in the
        #order specified in p.values
        i=0
        f=open(self._salib_paramFile,'w')
        for p in self.params:
            #map each column of _samples to a parameter, using the inverse cdf to transform it
            #into the appropriate distribution.
            p.values = p.pdf.ppf(self._samples[:,i])          
            i+=1
            f.write('{}\t{}\t{}\n'.format(p.name,p.pdf.range[0],p.pdf.range[1]))
            
            if hasattr(p, 'use_samples_val') and p.use_samples_val:
                print("Warning: ignoring option 'use_samples_val' for {}".format(p.name))
                
        f.close()

        #save the samples, as constructed by SALib
        np.savetxt(self._salib_realizationsFile,self._samples)        
        
        
    # Returns a list of name,value tuples
    # For example, [('t', 1.0), ('freq', 133862.0)]
    def get_args(self):
        for i in xrange(self._start_at, self.num):
            yield [(p.name, p.values[i],p.description) for p in self.params]

    def _do_pdf(self, hf, data):
        if self.response:
            print('Morris method does not support creating response surfaces')
            raise ValueError            
        else:
            pdf = ExperimentalPDF(data, fit=0)
            mean = np.mean(data)
            dev = np.std(data)
            print "Mean   = %s" % mean
            print "StdDev = %s" % dev
            
            #############
            #analyze results
            ############
            
            #N(D+1) x D            
            realizations=np.empty((np.size(data,0),len(self.params)))
            
            #retrieve the paramter samples in the same order as given to SALib
            i=0
            for p in self.params:
                aParam=unpickle(hf['/input/params'][p.name].value) 
                
                # get the values
                realizations[:,i]=aParam.values
                i+=1
 
            #check to make sure the order in which the parameters were initially sampled by SALib
            #was the order in which they were actually sampled by puq
            np.savetxt(self._salib_realizationsFile_verify,realizations)
            if os.path.getsize(self._salib_realizationsFile_verify) == os.path.getsize(self._salib_realizationsFile):                
                if not filecmp.cmp(self._salib_realizationsFile_verify, self._salib_realizationsFile, shallow=False):
                    raise Exception('The order in which the parameter samples were constructed is different than the sampled order!')
            else:
                raise Exception('The order in which the parameter samples were constructed is different than the sampled order!')
            
            #get the outputs
            outputs=hf['/output/data']
            numputputs=len(outputs)
            
            #SALib expects each output variable in a single column
            np.savetxt(self._salib_analysisFile,data)
            
            #Note: the delimiters for all the files passed to the analyze function must be the same
            s=SAa.morris.analyze(self._salib_paramFile,self._salib_realizationsFile,
                self._salib_analysisFile,column=0)
            
            #put things in the same format as the smolyak module
            sens={}            
            for key,val in s.iteritems():
                sens[key]={'u':val[0],'std': val[1], 'ustar': val[2],'ustar_conf95':val[3]}
                #senstxt+='{}\t{}\t{}\t{}'.format(key,val[0],val[1],val[2],val[3])
            
            sorted_list = sorted(sens.items(), lambda x, y: cmp(y[1]['ustar'], x[1]['ustar']))                
            
            try:
                os.remove(self._salib_paramFile)
                os.remove(self._salib_realizationsFile)
                os.remove(self._salib_realizationsFile_verify)
                os.remove(self._salib_analysisFile)
            except Exception,e:
                print("error deleting SALib temp files. " + str(e))
            
            return [('pdf', pickle(pdf)), ('samples', data), ('mean', mean), ('dev', dev),
                    ('sensitivity',pickle(sorted_list))]

    def analyze(self, hf):
        debug('')
        process_data(hf, 'morris', self._do_pdf)
        self._hf=hf

    def extend(self, numtrajectories,levels,gridjump,):
        if num <= 0:
            print "Morris extend requires a valid num argument."
            raise ValueError

        #TODO: when correlation is implemented, only allow extending if
        #the samples are uncorrelated
        samples=SAs.morris_oat.sample(N=numtrajectories,D=len(self.params),
                    num_levels=self.levels,grid_jump=self.gridjump)
                    
        i=0    
        for p in self.params:
            if self.response:
                print('Morris method does not support creating response surfaces')
                raise ValueError
                #p.values = np.concatenate((p.values, UniformPDF(*p.pdf.range).random(num)))
            else:
                newvalues= p.pdf.ppf(samples[:,i])
                p.values = np.concatenate((p.values, newvalues))
            i+=1
        self._start_at = self.num
        self.num += num
