"""
This file is part of PUQ
Copyright (c) 2013 PUQ Authors
See LICENSE file for terms.
"""
import os, shutil,optparse,shlex

class TestProgram(object):
    """
    Class implementing a TestProgram object representing the
    simulation to run.

    Args:
      name(string): Name of the program. This is the executable if
        no *exe* is defined.
      exe(string): An executable command template to run. Strings of
        the form '$var' are replaced with the value of *var*.
        See python template strings
        (`<http://docs.python.org/2/library/string.html#template-strings>`_)
      desc: Optional description of the test program.
      newdir(boolean): Run each job in its own directory.  Necessary
        if the simulation generates output files.  Default is False.
      infiles(list): If *newdir* is True, then this is an optional
        list of files that should be copied to each new directory.
      outfiles(list): An optional list of files that will be saved
        into the HDF5 file upon completion. The files will be in
        /output/jobs/n where 'n' is the job number.
      paramsByFile(boolean): If True, passes parameters to the TestProgram
        via a file rather than on the command line. The file name is 
        specified via - -paramsFile=xxx in the exe string.
        This option must be used with newdir=True. See Example 3.

    Example1::

      p1 = UniformParameter('x', 'x', min=-2, max=2)
      p2 = UniformParameter('y', 'y', min=-2, max=2)

      prog = TestProgram('./rosen_prog.py', desc='Rosenbrock Function')

      # or, the equivalent using template strings

      prog = TestProgram(exe='./rosen_prog.py --x=$x --y=$y',
        desc='Rosenbrock Function')


    Example2::

      # Using newdir and infiles. Will run each job in a new directory
      # with a copy of all the infiles.

      prog = TestProgram('PM2', newdir=True, desc='MPM Scaling',
        infiles=['pm2geometry', 'pm2input', 'pmgrid_geom.nc',
        'pmpart_geom.nc'])
        
    Example3::

      # Using newdir and paramsByFile
      # In this case, all parameters to rosen_prog.py located in the same directory
      # as this script will be passed in the file named input_params.txt
      # located in a subdirectory of the control script's directory. Ie., for the
      # example below, the file structure is the following (assuming this script
      # is named rosen.py contained in a directory called Rosen)
      # Rosen
      #   |_ rosen.py
      #   |_ rosen_prog.py
      #   |_ Run 1
      #       |__ input_params.txt
      #   |_ Run 2
      #       |__ input_params.txt
      #      .
      #      .
      #      .
      # 
      # input_params.txt contains 3 columns, separated by whitespace.
      # The first column is the parameter name, the second is the parameter value, 
      # the third is the parameter description.
      #
      # Note: the contents of input_params.txt can be loaded using numpy's loadtxt
      # with record-data type.

      prog = TestProgram(exe='python ../rosen_prog.py --paramsFile=input_params.txt',
        newdir=True, desc='Rosenbrock Function')

    """

    def __init__(self, name='', exe='', newdir=False, infiles='', desc='', outfiles='',
                    paramsByFile=False):
        self.name = name
        self.newdir = newdir
        self.infiles = infiles
        self.outfiles = outfiles
        self.exe = exe
        if self.name == '' and self.exe == '':
            raise ValueError("name or exe must be set.")
        self.desc = desc
        
        if paramsByFile and not newdir:
            raise ValueError("newdir must be set if paramsByFile is used")
        self.paramsByFile=paramsByFile

    def setup(self, dirname):
        if self.newdir:
            os.makedirs(dirname)
            if self.infiles:
                for src in self.infiles:
                    shutil.copy(src, dirname)
            return dirname
        else:
            return ''

    def cmd(self, args):
        args=[(p,v) for p,v,d in args]
        if not self.exe:
            arglist = ' '.join(['--%s=%s' % (p, v) for p, v in args])
            return '%s %s' % (self.name, arglist)
        exe = self.exe
        if exe.find('%1') > 0:
            # old style - deprecated
            for i in range(len(args), 0, -1):
                name, val  = args[i-1]
                mstr = '%%%d' % i
                exe = exe.replace(mstr, str(val))
        else:
            from string import Template
            t = Template(exe)
            exe = t.substitute(dict(args))
        return exe
     
    def cmdByFile(self,args,directory):
        #builds a command for the host to execute where the
        #parameters are passed in a file instead of the command line.
        #The relative path and name of the file are passed on the command line
        #by the job runner,
        #using the special command line argument '--paramsFile'
        #which is a reserved name (see check_name in parameter.py).
        
        #args is a list of tuples and comes from psweep.get_args via 
        #hosts.add_jobs and psweep.run        
        if "--paramsFile" not in self.exe:
            raise Exception("paramsByFile=True specified in TestProgram constructor but '--paramsFile' argument not set in the exe argument of the constructor")
            
        parser=optparse.OptionParser()
        parser.add_option("--paramsFile", action="store",type="string")
        (options, p_args) = parser.parse_args(shlex.split(self.exe))
        if options.paramsFile==None:
            raise Exception("'--paramsFile' was specified but no file name given!")
                
        #build the output file
        fname=os.path.join(directory,options.paramsFile)
        f=open(fname,'w')
        for p,v,d in args:
            f.write("{}\t\t\t{}\t\t\t\t\t{}\n".format(p,v,d))
        f.close()
        
        return self.exe
