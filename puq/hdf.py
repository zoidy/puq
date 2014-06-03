"""
Convenience functions that read or write to the HDF5 file
"""

"""
This file is part of PUQ
Copyright (c) 2013 PUQ Authors
See LICENSE file for terms.
"""

import h5py
from puq.jpickle import unpickle
from functools import wraps

def hdf5_wrap(func):
    @wraps(func)
    def wrapped(hf, *args, **kargs):
        close = False
        if type(hf) == str:
            hf = h5py.File(hf, 'r')
            close = True
        res = func(hf, *args, **kargs)
        if close:
            hf.close()
        return res
    return wrapped

@hdf5_wrap
def get_output_names(hf):
    """
    get_output_names(hf)

    Returns a list of the output variables names in the HDF5 file.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.

    Returns:
      A sorted list of the output variable names in the HDF5 file.
    """
    return sorted(map(str, hf['/output/data'].keys()))

@hdf5_wrap
def set_result(hf, var, data, desc=''):
    """
    set_result(hf, var, data, desc='')

    Sets values of the output variable in the HDF5 file.
    Writes array to '/output/data/**var**'.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
      var : Output variable name.
      data : Array of data to write.
      desc : Description.
    """
    try:
        del hf['/output/data/%s' % var]
    except:
        pass
    hf['/output/data/%s' % var] = data
    hf['/output/data/%s' % var].attrs['description'] = desc

@hdf5_wrap
def get_result(hf, var=None):
    """get_result(hf, var=None)

    Returns an array containing the values of the output variable.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
      var : Output variable name. Only required if there is more than
        one output variable.
    Returns:
      An array
    Raises:
      ValueError: if **var** is not found or **var** is None and there
        are multiple output variables.
    """
    if not '/output/data' in hf:
        return []

    output_variables = get_output_names(hf)
    if len(output_variables) == 0:
        return []

    if var and not var in output_variables:
        print "Variable %s not found in output data" % var
        raise ValueError
    if not var:
        if len(output_variables) > 1:
            print "Output data contains multiple variables."
            print "You must indicate which you want."
            raise ValueError
        var = output_variables[0]

    return hf['/output/data/%s' % var].value

@hdf5_wrap
def get_param_names(hf):
    """get_param_names(hf)

    Returns a list of the input parameter names in the HDF5 file.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
    """
    parameters = get_params(hf)
    return [p.name for p in parameters]

@hdf5_wrap
def get_params(hf):
    """get_params(hf)

    Returns a list of arrays of input parameter values.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
    """
    return [unpickle(hf['/input/params'][p].value) for p in hf['/input/params']]

@hdf5_wrap
def data_description(hf, var):
    """data_description(hf, var)

    Returns the description of an output variable. If the
    description is empty, returns the variable name.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
      var: Output variable name.
    """
    desc = hf['/output/data/%s' % var].attrs['description']
    if desc:
        return desc
    return var

@hdf5_wrap
def param_description(hf, var):
    """param_description(hf, var)

    Returns the description of an input variable. If the
    description is empty, returns the variable name.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
      var: Input parameter name.
    """
    desc = unpickle(hf['/input/params/%s' % var].value).description
    if desc:
        return desc
    return var

@hdf5_wrap
def get_response(hf, var):
    """get_response(hf, var)

    Returns the response function for an output variable.

    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
      var: Output variable name.
    """
    psweep = hf.attrs['UQtype']
    return unpickle(hf['/%s/%s/response' % (psweep, var)].value)
    
@hdf5_wrap
def get_sensitivity(hf, var):
    """get_sensitivity(hf, var).

    Returns the sensitivity indices for var in a dictionary with keys equal to 
    parameter names and values consisting of dictionaries with keys equal to sensitivity indices.

    The keys in the sub dictionaries will vary depending on the type of sensitivity analysis 
    (Smolyak or Morris) but will contain at least 'ustar' and 'std'. Morris also contains 'u' and
    'ustar_conf95'
    Args:
      hf: An open HDF5 filehandle or a string containing the HDF5
        filename to use.
      var: Output variable name.
    """
    psweep = hf.attrs['UQtype']
    if not '/%s/%s/sensitivity' % (psweep, var) in hf:
        print("Sensitivity indices weren't compute for output '{}'".format(var))
        raise ValueError
        
    return unpickle(hf['/%s/%s/sensitivity' % (psweep, var)].value)
