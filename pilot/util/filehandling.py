#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Paul Nilsson, paul.nilsson@cern.ch, 2017-2018

import os
import time
import uuid
import tarfile
from collections import deque
from shutil import copy2

from pilot.common.exception import PilotException, ConversionFailure, FileHandlingFailure, MKDirFailure, NoSuchFile
from pilot.util.container import execute

import logging
logger = logging.getLogger(__name__)


def get_pilot_work_dir(workdir):
    """
    Return the full path to the main PanDA Pilot work directory. Called once at the beginning of the batch job.

    :param workdir: The full path to where the main work directory should be created
    :return: The name of main work directory
    """

    jobworkdir = "PanDA_Pilot2_%d_%s" % (os.getpid(), str(int(time.time())))
    return os.path.join(workdir, jobworkdir)


def create_pilot_work_dir(workdir):
    """
    Create the main PanDA Pilot work directory.
    :param workdir: Full path to the directory to be created
    :raises PilotException: MKDirFailure.
    :return:
    """

    try:
        os.makedirs(workdir)
        os.chmod(workdir, 0770)
    except Exception as e:
        raise MKDirFailure(e)


def read_file(filename):
    """
    Open, read and close a file.
    :param filename: file name (string).
    :return: file contents (string).
    """

    out = ""
    f = open_file(filename, 'r')
    if f:
        out = f.read()
        f.close()

    return out


def write_file(filename, contents):
    """
    Write the given contents to a file.

    :param filename: file name (string).
    :param contents: file contents (string).
    :raises PilotException: FileHandlingFailure.
    :return: True if successful, otherwise False.
    """

    status = False

    f = open_file(filename, 'w')
    if f:
        try:
            f.write(contents)
        except IOError as e:
            raise FileHandlingFailure(e)
        else:
            status = True
        f.close()

    return status


def open_file(filename, mode):
    """
    Open and return a file pointer for the given mode.
    Note: the caller needs to close the file.

    :param filename: file name (string).
    :param mode: file mode (character).
    :raises PilotException: FileHandlingFailure.
    :return: file pointer.
    """

    f = None
    if os.path.exists(filename):
        try:
            f = open(filename, mode)
        except IOError as e:
            raise FileHandlingFailure(e)
    else:
        raise NoSuchFile("File does not exist: %s" % filename)

    return f


def get_files(pattern="*.log"):
    """
    Find all files whose names follow the given pattern.

    :param pattern: file name pattern (string).
    :return: list of files.
    """

    files = []
    cmd = "find . -name %s" % pattern
    exit_code, stdout, stderr = execute(cmd)
    if stdout:
        # remove last \n if present
        if stdout.endswith('\n'):
            stdout = stdout[:-1]
        files = stdout.split('\n')

    return files


def tail(filename, nlines=10):
    """
    Return the last n lines of a file.

    :param filename: name of file to do the tail on (string).
    :param nlines: number of lines (int).
    :return: file tail (list)
    """

    exit_code, stdout, stderr = execute('tail -%d %s' % (nlines, filename))
    return stdout


def convert(data):
    """
    Convert unicode data to utf-8.

    Usage examples:
    1. Dictionary:
      data = {u'Max': {u'maxRSS': 3664, u'maxSwap': 0, u'maxVMEM': 142260, u'maxPSS': 1288}, u'Avg':
             {u'avgVMEM': 94840, u'avgPSS': 850, u'avgRSS': 2430, u'avgSwap': 0}}
    convert(data)
      {'Max': {'maxRSS': 3664, 'maxSwap': 0, 'maxVMEM': 142260, 'maxPSS': 1288}, 'Avg': {'avgVMEM': 94840,
       'avgPSS': 850, 'avgRSS': 2430, 'avgSwap': 0}}
    2. String:
      data = u'hello'
    convert(data)
      'hello'
    3. List:
      data = [u'1',u'2','3']
    convert(data)
      ['1', '2', '3']

    :param data: unicode object to be converted to utf-8
    :return: converted data to utf-8
    """

    import collections
    if isinstance(data, basestring):
        return str(data)
    elif isinstance(data, collections.Mapping):
        return dict(map(convert, data.iteritems()))
    elif isinstance(data, collections.Iterable):
        return type(data)(map(convert, data))
    else:
        return data


def read_json(filename):
    """
    Read a dictionary with unicode to utf-8 conversion

    :param filename:
    :raises PilotException: FileHandlingFailure, ConversionFailure
    :return: json dictionary
    """

    dictionary = None
    f = open_file(filename, 'r')
    if f:
        from json import load
        try:
            dictionary = load(f)
        except PilotException as e:
            raise FileHandlingFailure(e.get_detail())
        else:
            f.close()

            # Try to convert the dictionary from unicode to utf-8
            if dictionary != {}:
                try:
                    dictionary = convert(dictionary)
                except Exception as e:
                    raise ConversionFailure(e.message)

    return dictionary


def write_json(filename, dictionary):
    """
    Write the dictionary to a JSON file.

    :param filename:
    :param dictionary:
    :raises PilotException: FileHandlingFailure
    :return: status (boolean)
    """

    status = False

    from json import dump
    try:
        fp = open(filename, "w")
    except IOError as e:
        raise FileHandlingFailure(e)
    else:
        # Write the dictionary
        try:
            dump(dictionary, fp, sort_keys=True, indent=4, separators=(',', ': '))
        except PilotException as e:
            raise FileHandlingFailure(e.get_detail())
        else:
            status = True
        fp.close()

    return status


def touch(path):
    """
    Touch a file and update mtime in case the file exists.

    :param path:
    :return:
    """

    with open(path, 'a'):
        os.utime(path, None)


def remove_empty_directories(src_dir):
    """
    Removal of empty directories in the given src_dir tree.
    Only empty directories will be removed.

    :param src_dir: directory to be purged of empty directories.
    :return:
    """

    for dirpath, subdirs, files in os.walk(src_dir, topdown=False):
        if dirpath == src_dir:
            break
        try:
            os.rmdir(dirpath)
        except OSError:
            pass


def remove(path):
    """
    Remove file.
    :param path: path to file (string).
    :return: 0 if successful, -1 if failed (int)
    """

    try:
        os.remove(path)
    except OSError as e:
        logger.warning("failed to remove file: %s, %s" % (e.errno, e.strerror))
        return -1
    return 0


def remove_files(workdir, files):
    """
    Remove all given files from workdir.

    :param workdir: working directory (string).
    :param files: file list.
    :return: exit code (0 if all went well, -1 otherwise)
    """

    ec = 0
    if type(files) != list:
        logger.warning('files parameter not a list: %s' % str(type(list)))
        ec = -1
    else:
        for f in files:
            _ec = remove(os.path.join(workdir, f))
            if _ec != 0 and ec == 0:
                ec = _ec

    return ec


def tar_files(wkdir, excludedfiles, logfile_name, attempt=0):
    """
    Tarring of files in given directory.

    :param wkdir: work directory (string)
    :param excludedfiles: list of files to be excluded from tar operation (list)
    :param logfile_name: file name (string)
    :param attempt: attempt number (integer)
    :return: 0 if successful, 1 in case of error (int)
    """

    to_pack = []
    pack_start = time.time()
    for path, subdir, files in os.walk(wkdir):
        for file in files:
            if file not in excludedfiles:
                rel_dir = os.path.relpath(path, wkdir)
                file_rel_path = os.path.join(rel_dir, file)
                file_path = os.path.join(path, file)
                to_pack.append((file_path, file_rel_path))
    if to_pack:
        try:
            logfile_name = os.path.join(wkdir, logfile_name)
            log_pack = tarfile.open(logfile_name, 'w:gz')
            for f in to_pack:
                log_pack.add(f[0], arcname=f[1])
            log_pack.close()
        except IOError:
            if attempt == 0:
                safe_delay = 15
                logger.warning('i/o error - will retry in {0} seconds'.format(safe_delay))
                time.sleep(safe_delay)
                tar_files(wkdir, excludedfiles, logfile_name, attempt=1)
            else:
                logger.warning("continues i/o errors during packing of logs - job will fail")
                return 1

    for f in to_pack:
        remove(f[0])

    remove_empty_directories(wkdir)
    pack_time = time.time() - pack_start
    logger.debug("packing of logs took {0} seconds".format(pack_time))

    return 0


def copy(path1, path2):
    """
    Copy path1 to path2.

    :param path1: file path (string).
    :param path2: file path (string).
    :raises PilotException: FileHandlingFailure, NoSuchFile
    :return:
    """

    if not os.path.exists(path1):
        logger.warning('file copy failure: path does not exist: %s' % path1)
        raise NoSuchFile("File does not exist: %s" % path1)

    try:
        copy2(path1, path2)
    except IOError as e:
        logger.warning("exception caught during file copy: %s" % e)
        raise FileHandlingFailure(e)
    else:
        logger.info("copied %s to %s" % (path1, path2))


def find_executable(name):
    """
    Is the command 'name' available locally?

    :param name: command name (string).
    :return: full path to command if it exists, otherwise empty string.
    """

    from distutils.spawn import find_executable
    return find_executable(name)


def get_directory_size(directory="."):
    """
    Return the size of the given directory in B.

    :param directory: directory name (string).
    :return: size of directory (int).
    """

    size = 0

    exit_code, stdout, stderr = execute('du -sk %s' % directory, shell=True)
    if stdout is not None:
        try:
            # convert to int and B
            size = int(stdout.split()[0]) * 1024
        except Exception as e:
            logger.warning('exception caught while trying convert dirsize: %s' % e)

    return size


def add_to_total_size(path, total_size):
    """
    Add the size of file in the given path to the total size of all in/output files.

    :param path: path to file (string).
    :param total_size: prior total size of all input/output files (long).
    :return: total size of all input/output files (long).
    """

    if os.path.exists(path):
        # Get the file size
        fsize = get_local_file_size(path)
        if fsize:
            logger.info("size of file %s: %d B" % (path, fsize))
            total_size += long(fsize)
    else:
        logger.warning("skipping file %s since it is not present" % path)

    return total_size


def get_local_file_size(filename):
    """
    Get the file size of a local file.

    :param filename: file name (string).
    :return: file size (int).
    """

    file_size = None

    if os.path.exists(filename):
        try:
            file_size = os.path.getsize(filename)
        except Exception as e:
            logger.warning("failed to get file size: %s" % e)
    else:
        logger.warning("local file does not exist: %s" % filename)

    return file_size


def get_guid():
    """
    Generate a GUID using the uuid library.
    E.g. guid = '92008FAF-BE4C-49CF-9C5C-E12BC74ACD19'

    :return: a random GUID (string)
    """

    return str(uuid.uuid4()).upper()


def get_table_from_file(filename, header=None, separator="\t", convert_to_float=True):
    """
    Extract a table of data from a txt file.
    E.g.
    header="Time VMEM PSS RSS Swap rchar wchar rbytes wbytes"
    or the first line in the file is
    Time VMEM PSS RSS Swap rchar wchar rbytes wbytes
    each of which will become keys in the dictionary, whose corresponding values are stored in lists, with the entries
    corresponding to the values in the rows of the input file.

    The output dictionary will have the format
    {'Time': [ .. data from first row .. ], 'VMEM': [.. data from second row], ..}

    :param filename: name of input text file, full path (string).
    :param header: header string.
    :param separator: separator character (char).
    :param convert_to_float: boolean, if True, all values will be converted to floats.
    :return: dictionary.
    """

    tabledict = {}
    keylist = []  # ordered list of dictionary key names

    try:
        f = open_file(filename, 'r')
    except Exception as e:
        logger.warning("failed to open file: %s, %s" % (filename, e))
    else:
        firstline = True
        for line in f:
            fields = line.split(separator)
            if firstline:
                firstline = False
                tabledict, keylist = _define_tabledict_keys(header, fields, separator)
                if not header:
                    continue

            # from now on, fill the dictionary fields with the input data
            i = 0
            for field in fields:
                # get the corresponding dictionary key from the keylist
                key = keylist[i]
                # store the field value in the correct list
                if convert_to_float:
                    try:
                        field = float(field)
                    except Exception as e:
                        logger.warning("failed to convert %s to float: %s (aborting)" % (field, e))
                        return None
                tabledict[key].append(field)
                i += 1
        f.close()

    return tabledict


def _define_tabledict_keys(header, fields, separator):
    """
    Define the keys for the tabledict dictionary.
    Note: this function is only used by parse_table_from_file().

    :param header: header string.
    :param fields: header content string.
    :param separator: separator character (char).
    :return: tabledict (dictionary), keylist (ordered list with dictionary key names).
    """

    tabledict = {}
    keylist = []

    if not header:
        # get the dictionary keys from the header of the file
        for key in fields:
            # first line defines the header, whose elements will be used as dictionary keys
            if key == '':
                continue
            if key.endswith('\n'):
                key = key[:-1]
            tabledict[key] = []
            keylist.append(key)
    else:
        # get the dictionary keys from the provided header
        keys = header.split(separator)
        for key in keys:
            if key == '':
                continue
            if key.endswith('\n'):
                key = key[:-1]
            tabledict[key] = []
            keylist.append(key)

    return tabledict, keylist
