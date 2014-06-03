************
Introduction
************

:Version: 2.2
:Authors: Martin Hunt, Fernando Rios
:Web site: https://github.com/zoidy/puq
:Documentation: http://martin-hunt.github.io/puq/
:Copyright: This document has been placed in the public domain.
:License: MIT License.

See https://github.com/martin-hunt/puq for the original readme.

Purpose
=======

This fork aims to port some/most of puq to the Windows platform and add some functionality.

Functionality
========================
In addition to running on Windows, this version of puq adds the following functionality:

- Ability to conduct sensitivity analysis using the Morris method (requires 
  `my version <https://github.com/zoidy/SALib>`_  of the SALib library)
- Ability to conduct a dry run (all steps of the run are shown, including the command lines to 
  be executed, except the actual model is not run.) In order to have a complete output file, a dummy
  output value is used.
- Ability to specify the number of samples to use when generating a PDF of a response surface
  from a script.

Installation
============

The installation procedure and dependencies are the same as https://github.com/martin-hunt/puq.
To conduct a Morris sensitivity analysis, the version of SALib located at 
https://github.com/zoidy/SALib is required.
To build sparse_grid_cc you will need a C++ compiler such as gcc. If using MinGW, install 
(for a 32 bit system),

- mingw32-base (I used 2013072200)
- mingw32-gcc-g++ (I used 4.8.1-4)

and make sure mingw32\bin is on your path. Then running the installation::
    
    python setup.py
    
will cause sparse_grid_cc to build. Afterwards, put this library into the site-packages folder.

What works
==========
Most functionality of the original puq should work. At the moment, only the InteractiveHost
is supported.


