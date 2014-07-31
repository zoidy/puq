"""
.. module:: constant
    :synopsis: This module implements constants such that they may be "sampled" by puq, similar to pdfs.

.. moduleauthor:: Fernando Rios

This file is part of PUQ
Copyright (c) 2013 PUQ Authors
See LICENSE file for terms.
"""

"""
Class implementing a constant such that it may be used as a drop-in replacement for a
PDF, when needed.
"""

import numpy as np

class Constant(object):
    """
    Create a Constant object.

    Use this to create a constant such that it may be used to replace a PDF. E.g.,
    If a PDF should be considered a constant instead, this class can be used as a
    drop-in replacement

    Args:
      value: the constant value
    """

    def __init__(self,value):
        if value==None:
            raise ValueError("Constant value must be specified")

        if isinstance(value, np.ndarray):
            val=np.r_[value[0]]
        else:
            val=np.r_[value]
    
        #need to copy it or else jsonpickle will fail when unpickling with
        # IndexError: list index out of range
        #when running puq analyze
        self.data=np.copy(val)
        range = 0

        #x=the x value (ie the constant itself)
        #y=the value of the "pdf" at x
        #cdfy=the value of the "cdf" at x
        self.x = np.copy(val)
        self.y=np.r_[np.inf] #not really but we need a number here
        self.cdfy=val   #not really but we need a number here
        
        self.mean = val[0]
        self.dev = 0

    @property
    def range(self):
        """
        The range for the PDF. For PDFs with long tails,
        it is truncated to 99.99% by default.  You can
        customize this by setting options['pdf']['range'].

        Returns:
          A tuple containing the min and max.
        """
        return (self.data[0], self.data[-1])

    @property
    def srange(self):
        """
        The small range for the PDF. For PDFs with long tails,
        it is truncated to 99.8% by default.  You can
        customize this by setting options['pdf']['srange'].

        Returns:
          A tuple containing the min and max.
        """
        self.range()

    def pdf(self, arr):
        """
        Computes the Probability Density Function (PDF) for some values.

        Args:
          arr: Array of x values.
        Returns:
          Array of pdf(x).
        """
        return np.inf + np.zeros(shape(arr))

    def cdf(self, arr):
        """
        Computes the Cumulative Density Function (CDF) for some values.

        Args:
          arr: Array of x values.
        Returns:
          Array of cdf(x).
        """
        return (arr>=self.data)*1

    def ppf(self, arr):
        """
        Percent Point Function (inverse CDF)

        Args:
          arr: Array of x values.
        Returns:
          Array of ppf(x).
        """
        return self.data + np.zeros(np.shape(arr))

    def lhs1(self, num):
        """
        Latin Hypercube Sample in [-1,1] for this distribution.

        The order of the numbers
        in the array is random, so it can be combined with other arrays
        to form a latin hypercube. Note that this can return values
        outside the range [-1,1] for distributions with long tails.
        This method is used by :mod:`puq.Smolyak`.

        Args:
          num: Number of samples to generate.
        Returns:
          1D array of length *num*.
        """        
        return self.data + np.zeros(num)

    def ds1(self, num):
        '''
        Generates a descriptive sample in [-1,1] for this distribution.

        The order of the numbers
        in the array is random, so it can be combined with other arrays
        to form a latin hypercube. Note that this *can* return values
        outside the range [-1,1] for distributions with long tails.
        This method is used by :mod:`puq.Smolyak`.

        :param num: Number of samples to generate.
        :returns: 1D array of length *num*.
        '''
        return self.data + np.zeros(num)

    def lhs(self, num):
        '''
        Latin Hypercube Sample for this distribution.

        The order of the numbers in the array is random, so it can be
        combined with other arrays to form a latin hypercube.
        This method is used by :class:`LHS`.

        :param num: Number of samples to generate.
        :returns: 1D array of length *num*.
        '''
        return self.data + np.zeros(num)

    def ds(self, num):
        '''
        Generates a descriptive sample for this distribution.

        The order of the numbers
        in the array is random, so it can be combined with other arrays
        to form a latin hypercube.
        This method is used by :class:`LHS`.

        :param num: Number of samples to generate.
        :returns: 1D array of length *num*.
        '''
        return self.data + np.zeros(num)

    def random(self, num):
        """
        Generate random numbers fitting this parameter's distribution.

        This method is used by :class:`MonteCarlo`.

        :param num: Number of samples to generate.
        :returns: 1D array of length *num*.
        """
        return self.data + np.zeros(num)

    def __neg__(self):
        return self.data*-1

    def __radd__(self, b):
        #print "__radd %s %s" % (self,b)
        return self._nadd(b)

    def _nadd(self, b):
        #print "_nadd %s" % (b)
        # add a scalar to a PDF
        return self.data+b

    def __add__(self, b):
        return self._nadd(b)

    def __rsub__(self, b):
        return b-self.data

    def __sub__(self, b):
        'Subtract two PDFs, returning a new PDF'
        return self.__add__(-b)

    def __rmul__(self, b):
        return self._nmul(b)

    def _nmul(self, b):
        return b * self.data

    def __mul__(self, b):
        return self._nmul(b)

    def _ndiv(self, b):
        if b == 0:
            raise ValueError("Cannot divide by 0.")
        return self.data/b

    def __rdiv__(self, b):
        if self.data==0:
            raise ValueError("cannot divide by 0")
        return b/self.data

    def __truediv__(self, b):
        return self.__div__(b)

    def __div__(self, b):
        return self._ndiv(b)
        
    @property
    def mode(self):
        """
        Find the mode of the PDF.  The mode is the x value at which pdf(x)
        is at its maximum.  It is the peak of the PDF.
        """        
        return self.data[0]

    def __str__(self):
        _str = "Value: {}".format(self.data[0])
        return _str

    def plot(self, color='', fig=False):
        """
        Plot a PDF.

        :param color: Optional color for the plot.
        :type color: String.
        :param fig: Create a new matplotlib figure to hold the plot.
        :type fig: Boolean.
        :returns: A list of lines that were added.
        """
        if fig:
            plt.figure()
        if color:            
            return plt.plot([self.data[0],0], [self.data[0],1], color=color)
        else:
            return plt.plot([self.data[0],0], [self.data[0],1], color='g')

    # ipython pretty print method
    def _repr_pretty_(self, p, cycle):
        if cycle:
            return
        self.plot()
        p.text(self.__str__())

