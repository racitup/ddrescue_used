"""
Module for cloning filesystems.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import helpers, fsmeta, fs
import logging, os

# For debugging: import pdb; pdb.set_trace() # DEBUG

def _clone(clonemeta, options, devsize, partinfo):
    "Transfers filesystems that support it using a clone application."
    # (devpath, start, size, fstype, clonemeta & clonedata results)
    outlist = []
    image = helpers.image(options)
    create_image(image, devsize)
    for devpath, start, size, fstype, metaresult, dataresult in partinfo:
        #showsizes(image) # DEBUG
        partn = {}
        partn['SStart'] = start
        partn['Size'] = size
        clonepath = helpers.randpath(options, 'clone.')
        with helpers.AttachLoop(image, 'rw', partn=partn) as loop:
            try:
                cmd2 = None
                if clonemeta:
                    cmd2 = fs.clonemeta2(fstype, clonepath, loop)
                    if cmd2:
                        cmd1 = fs.clonemeta1(fstype, devpath, clonepath)
                    else:
                        cmd1 = fs.clonemeta1(fstype, devpath, loop)
                else:
                    cmd1 = fs.clonedata(fstype, devpath, loop)
            except KeyError:
                outlist += [(devpath, start, size, fstype, None, None)]
                continue

            if cmd1:
                logging.info('Cloning {}: start={}, size={}, type={}'
                        .format(devpath, start, size, fstype))
                result = helpers.checkgcscmd(cmd1)
                if cmd2 and result:
                    result = helpers.checkgcscmd(cmd2)
                helpers.removefile(clonepath)
            else:
                result = None
        if clonemeta:
            outlist += [(devpath, start, size, fstype, result, None)]
        else:
            outlist += [(devpath, start, size, fstype, metaresult, result)]
    return outlist

clonemeta = lambda options, devsize, partinfo: _clone(True, options, devsize, partinfo)
clonedata = lambda options, devsize, partinfo: _clone(False, options, devsize, partinfo)

def showsizes(path):
    "Debug helper for finding allocated/apparent/ls and used sizes."
    helpers.get_procoutput(['du', '-h', path])
    helpers.get_procoutput(['du', '-h', '--apparent-size', path])

def create_image(image, devsize):
    "Check if the image exists, that it is the correct size, otherwise create."
    devsizeB = devsize*512
    if os.path.exists(image):
        imgsize = os.stat(image).st_size
        if imgsize == devsizeB:
            return
        elif imgsize == 0:
            os.remove(image)
        else:
            raise Exception('{} is not the correct size'.format(image))
    # Create a sparse file if possible
    proc = helpers.get_procoutput(['truncate', '-s', str(devsizeB), image])[0]
    if proc.returncode != 0:
        raise Exception('Could not allocate image file.')

