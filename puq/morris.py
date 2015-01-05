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
from puq.options import options
#import SALib.sample as SAs
#import SALib.analyze as SAa
from SALib.sample import morris_oat
from SALib.analyze import morris
from SALib.util import read_param_file
#import SALib.util as SAu
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
        
        #generate the parameters file for SALib
        f=open(self._salib_paramFile,'w')
        for p in self.params:
            f.write('{}\t{}\t{}\n'.format(p.name,0,1))
        f.close()
            
        #generate morris samples N(D+1) x D numpy array. Rows are realizations, columns are params
        #Each column is independent and between 0 and 1. The columns are the quantiles of the input pdfs.
        #TODO: allow for correlation (Rank correlation: can use Iman & Conover, see test_basepoint_correlation.py)
        self._samples=morris_oat.sample(N=num,param_file=self._salib_paramFile,
                                            num_levels=levels,grid_jump=gridjump)
        
        #puq will evaluate the output by picking a sample from each parameter. The order of
        #evaluation is given by the order specified in p.values
        i=0        
        for p in self.params:
            #map each column of _samples to a parameter, using the inverse cdf to transform it
            #into the appropriate distribution.
            p.values = p.pdf.ppf(self._samples[:,i])
            i+=1
            
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
        #called by util.process_data as the callback function.
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
            
            #retrieve the parameter samples in the same order as given to SALib
            i=0
            for p in self.params:
                aParam=unpickle(hf['/input/params'][p.name].value) 
                
                # get the values
                realizations[:,i]=aParam.values
                i+=1
 
            #check to make sure the order in which the parameters were initially sampled by SALib
            #was the order in which they were actually sampled by puq
            #--NOT NEEDED ANYMORE. puq samples in the order given in p.values. Also, if 
            #  params are not uniform distributions, this check will fail anyways.
            # np.savetxt(self._salib_realizationsFile_verify,realizations)
            # if os.path.getsize(self._salib_realizationsFile_verify) == os.path.getsize(self._salib_realizationsFile):                
                # if not filecmp.cmp(self._salib_realizationsFile_verify, self._salib_realizationsFile, shallow=False):
                    # print('Warning: The order in which the parameter samples were constructed is different than the sampled order!')
            # else:
                # print('Warning: The order in which the parameter samples were constructed is different than the sampled order!')
            
            #get the outputs. hf is the group of the output variable currently being processed
            #e.g., if the output is X, hf.name = '/morris/X'.
            #Note can also access the full hdf5 tree. Eg., hf['/outputs/data'] will given the
            #/outputs/data group, even though its not a subgroup of /morris/X           
            numoutputs=len(hf['/output/data'])
            self._num_outputs_processed+=1
            
            #save the output into its own file
            salib_analysisFile=os.path.splitext(self._salib_analysisFile)[0] + os.path.basename(hf.name) + '.txt'
            
            #SALib expects each output variable in a single column
            np.savetxt(salib_analysisFile,data)
            
            #Note: the delimiters for all the files passed to the analyze function must be the same
            s=morris.analyze(self._salib_paramFile,self._salib_realizationsFile,
                salib_analysisFile,column=0)
                
            #read the paramsFile to find the parameter names
            pf=read_param_file(self._salib_paramFile)
            
            #put things in the same format as the smolyak module
            sens={}
            for i,param_name in enumerate(pf['names']):
                sens[param_name]={'u':s['mu'][i],'std': s['sigma'][i], 'ustar': s['mu_star'][i],
                                  'ustar_conf95':s['mu_star_conf'][i]}
            
            sorted_list = sorted(sens.items(), lambda x, y: cmp(y[1]['ustar'], x[1]['ustar']))                
            
            try:
                if not options['keep']:
                    if self._num_outputs_processed==numoutputs:
                        #don't delete these until we've processed all outputs. unlike salib_analysisFile,
                        #the files below don't get recreated at each call to this function.
                        os.remove(self._salib_paramFile)
                        os.remove(self._salib_realizationsFile)
                    os.remove(salib_analysisFile)
                    #os.remove(self._salib_realizationsFile_verify)
                    pass
            except Exception,e:
                print("warning: couldn't delete all SALib temp files. " + str(e))
            
            return [('pdf', pickle(pdf)), ('samples', data), ('mean', mean), ('dev', dev),
                    ('sensitivity',pickle(sorted_list))]

    def analyze(self, hf):
        debug('')
        self._num_outputs_processed=0
        process_data(hf, 'morris', self._do_pdf)
        self._hf=hf

    def extend(self, numtrajectories,levels,gridjump,):
        if num <= 0:
            print "Morris extend requires a valid num argument."
            raise ValueError

        #TODO: when correlation is implemented, only allow extending if
        #the samples are uncorrelated
        samples=morris_oat.sample(N=numtrajectories,D=len(self.params),
                    num_levels=self.levels,grid_jump=self.gridjump)
                    
        i=0    
        for p in self.params:
            if self.response:
                print('Morris method does not support creating response surfaces')
                raise ValueError
            else:
                if hasattr(p, 'use_samples_val') and p.use_samples_val:
                    print("Warning: ignoring option 'use_samples_val' for {}".format(p.name))
                newvalues= p.pdf.ppf(samples[:,i])
                p.values = np.concatenate((p.values, newvalues))
            i+=1
        self._start_at = self.num
        self.num += num
