"""
Basic Monte Carlo Method

This file is part of PUQ
Copyright (c) 2013 PUQ Authors
See LICENSE file for terms.
"""

import numpy as np
from puq.util import process_data
from puq.psweep import PSweep
from logging import info, debug, exception, warning, critical
from puq.response import SampledFunc
from puq.jpickle import pickle
from puq.pdf import UniformPDF, ExperimentalPDF

class MonteCarlo(PSweep):
    """
    Class implementing Monte Carlo sampling.

    Args:
      params: Input list of :class:`Parameter`\s.
      num: Number of samples to use.
      response(boolean): Generate a response surface using the sample
        points.
      iteration_cb(function): A function to call after completion.
    """
    def __init__(self, params, num, response=True, iteration_cb=None):
        PSweep.__init__(self, iteration_cb)
        self.params = params
        num = int(num)
        self.num = num
        self.response = response
        self._start_at = 0

        if self.response:
            if hasattr(p, 'use_samples_val') and p.use_samples_val:
                #when constructing a response surface, ignore use_samples_val
                #since the surface must be constructed so as to cover the entire
                #rangem of the input parameters.
                print("Warning: ignoring option 'use_samples_val' for {}".format(p.name))
                
            # To generate a complete response surface, use Uniform distributions
            # with the same range as the original distributions.
            for p in self.params:
                p.values = UniformPDF(*p.pdf.range).random(num)
        else:
            for p in self.params:
                #only generate new samples if use_samples is false
                #see CustomParameter in parameter.py
                if hasattr(p, 'use_samples_val') and p.use_samples_val:
                    if np.size(p.values!=num):
                        raise Exception("Expected {} samples for parameter {}, found {}".format(num,p.name,np.size(p.values)))
                    ok = 0
                    try:
                    # are all the value arrays the same length?
                        ok = len(set([len(p.values) for p in params]))
                    except:
                        pass
                    if ok != 1:
                        raise ValueError('All parameters must have .values array of the same length')
                else:
                    p.values = p.pdf.random(num)

    # Returns a list of name,value tuples
    # For example, [('t', 1.0), ('freq', 133862.0)]
    # This is one realization of the parameters. Since this function
    # returns a generator which can be iterated like a list,
    # yielding an iterable list of lists of tuples.
    def get_args(self):
        for i in xrange(self._start_at, self.num):
            yield [(p.name, p.values[i],p.description) for p in self.params]

    def _do_pdf(self, hf, data):
        if self.response:
            # The response surface was built using Uniform distributions.
            # We are interested in the mean and deviation of the data
            # that would have been produced using the real PDFs. For this,
            # we need to compute a weighted mean and deviation
            weights = np.prod([p.pdf.pdf(p.values) for p in self.params], 0)
            tweight = np.sum(weights)

            mean = np.average(data, weights=weights)
            dev = np.sqrt(np.dot(weights, (data - mean)**2) / tweight)
            rsd = np.vstack(([p.values for p in self.params], data))
            rs = pickle(SampledFunc(*rsd, params=self.params))
            print "Mean   = %s" % mean
            print "StdDev = %s" % dev
            return [('response', rs), ('mean', mean), ('dev', dev)]
        else:
            pdf = ExperimentalPDF(data, fit=0)
            mean = np.mean(data)
            dev = np.std(data)
            print "Mean   = %s" % mean
            print "StdDev = %s" % dev
            return [('pdf', pickle(pdf)), ('samples', data), ('mean', mean), ('dev', dev)]

    def analyze(self, hf):
        debug('')
        process_data(hf, 'montecarlo', self._do_pdf)

    def extend(self, num):
        if num <= 0:
            print "Monte Carlo extend requires a valid num argument."
            raise ValueError
        for p in self.params:
            if self.response:
                p.values = np.concatenate((p.values, UniformPDF(*p.pdf.range).random(num)))
            else:
                p.values = np.concatenate((p.values, p.pdf.random(num)))
        self._start_at = self.num
        self.num += num
