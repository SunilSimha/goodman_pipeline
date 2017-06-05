from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import os
import sys
import time
import re
import pandas
import logging
import matplotlib.pyplot as plt
import numpy as np
from ccdproc import ImageFileCollection
from mpl_toolkits.mplot3d import Axes3D
from astropy.coordinates import EarthLocation
from astropy.time import Time, TimeDelta
from astroplan import Observer
from astropy import units as u
from .core import convert_time, get_twilight_time, ra_dec_to_deg

log = logging.getLogger('goodmanccd.nightorganizer')


class NightOrganizer(object):

    def __init__(self, full_path, instrument, technique, ignore_bias=False):
        """Initializes the NightOrganizer class

        This class contains methods to organize the data for processing. It will
        identify groups of OBJECTS, FLATS or COMPS (comparison lamps) whenever
        they exist. The product will be an object that will act as a data
        container.

        Args:
            args (object): Argparse object. Contains all the runtime arguments.
            night_dict (dict): A dictionary that contains full path, instrument
            and observational technique.

        """
        self.path = full_path
        self.instrument = instrument
        self.technique = technique
        self.ignore_bias = ignore_bias
        self.keywords = ['date',
                         'slit',
                         'date-obs',
                         'obstype',
                         'object',
                         'exptime',
                         'obsra',
                         'obsdec',
                         'grating',
                         'cam_targ',
                         'grt_targ',
                         'filter',
                         'filter2',
                         'gain',
                         'rdnoise']
        self.file_collection = None
        self.all_datatypes = None

        self.data_container = Night(path=self.path,
                                    instrument=self.instrument,
                                    technique=self.technique)

        self.day_time_data = None
        self.night_time_data = None

    def __call__(self):
        """Call method

        Creates a table with selected keywords that will allow to group the data
        in order to be classified according to the observational technique used,
        imaging or spectroscopy.

        Returns:
            data_container (object): Class used as storage unit for classified
            data.

        """

        ifc = ImageFileCollection(self.path, self.keywords)
        self.file_collection = ifc.summary.to_pandas()
        # add two columns that will contain the ra and dec in degrees
        # TODO (simon): This part creates a warning originated from Pandas.
        # TODO (cont): Fixit
        self.file_collection['radeg'] = ''
        self.file_collection['decdeg'] = ''
        for i in self.file_collection.index.tolist():

            radeg, decdeg = ra_dec_to_deg(self.file_collection.obsra.iloc[i],
                                          self.file_collection.obsdec.iloc[i])

            self.file_collection.radeg.iloc[i] = '{:.2f}'.format(radeg)
            self.file_collection.decdeg.iloc[i] = '{:.2f}'.format(decdeg)
            # now we can compare using degrees
        self.initial_checks()
        self.all_datatypes = self.file_collection.obstype.unique()
        if self.technique == 'Spectroscopy':
            print(self.data_container.is_empty)
            self.spectroscopy_night(file_collection=self.file_collection,
                                    data_container=self.data_container)
            print(self.data_container.is_empty)
        elif self.technique == 'Imaging':
            self.imaging_night()

        if self.data_container.is_empty:
            log.debug('data_container is empty')
            sys.exit('ERROR: There is no data to process!')
        else:
            log.debug('Returning classified data')
            return self.data_container

    def initial_checks(self):
        readout_confs = self.file_collection.groupby(['gain', 'rdnoise'])
        if len(readout_confs) > 1:

            log.warning('There are {:d} different readout modes in the '
                        'data.'.format(len(readout_confs)))

            log.info('Sleeping 10 seconds')
            time.sleep(10)

    @staticmethod
    def spectroscopy_night(file_collection, data_container):
        """Organizes data for spectroscopy

        This method identifies all combinations of nine **key** keywords that
        can set appart different objects with their respective calibration data
        or not. The keywords used are: GAIN, RDNOISE, GRATING, FILTER2,
        CAM_TARG,GRT_TARG, SLIT, OBSRA and OBSDEC.

        This method populates the `data_container` class attribute which is an
        instance of the class Night.
        A data group is an instance of a Pandas DataFrame.

        """

        print(file_collection)
        assert isinstance(file_collection, pandas.DataFrame)
        assert isinstance(data_container, Night)

        # obtain a list of timestamps of observing time
        # this will only be used for naming flats
        dateobs_list = file_collection['date-obs'].tolist()

        # get times for twilights, sunset an sunrise
        afternoon_twilight, morning_twilight, sun_set, sun_rise = \
            get_twilight_time(date_obs=dateobs_list)

        # set times in data container
        data_container.set_sun_times(sun_set,
                                     sun_rise)
        data_container.set_twilight_times(afternoon_twilight,
                                          morning_twilight)


        #process bias
        bias_collection = file_collection[file_collection.obstype == 'BIAS']

        bias_conf = bias_collection.groupby(
            ['gain',
             'rdnoise',
             'radeg',
             'decdeg']).size().reset_index().rename(columns={0: 'count'})

        # bias_conf
        for i in bias_conf.index:

            bias_group = bias_collection[
                ((bias_collection['gain'] == bias_conf.iloc[i]['gain']) &
                (bias_collection['rdnoise'] == bias_conf.iloc[i]['rdnoise']) &
                (bias_collection['radeg'] == bias_conf.iloc[i]['radeg']) &
                (bias_collection['decdeg'] == bias_conf.iloc[i]['decdeg']))]

            data_container.add_bias(bias_group=bias_group)

        # process non-bias i.e. flats and object ... and comp
        data_collection = file_collection[file_collection.obstype != 'BIAS']

        confs = data_collection.groupby(
            ['gain',
             'rdnoise',
             'grating',
             'filter2',
             'cam_targ',
             'grt_targ',
             'slit',
             'radeg',
             'decdeg']).size().reset_index().rename(columns={0: 'count'})

        for i in confs.index:

            data_group = data_collection[
                ((data_collection['gain'] == confs.iloc[i]['gain']) &
                (data_collection['rdnoise'] == confs.iloc[i]['rdnoise']) &
                (data_collection['grating'] == confs.iloc[i]['grating']) &
                (data_collection['filter2'] == confs.iloc[i]['filter2']) &
                (data_collection['cam_targ'] == confs.iloc[i]['cam_targ']) &
                (data_collection['grt_targ'] == confs.iloc[i]['grt_targ']) &
                (data_collection['slit'] == confs.iloc[i]['slit']) &
                (data_collection['radeg'] == confs.iloc[i]['radeg']) &
                (data_collection['decdeg'] == confs.iloc[i]['decdeg']))]

            data_container.add_data_group(data_group)
        return data_container

    def imaging_night(self):
        """Organizes data for imaging

        For imaging there is no discrimination regarding night data since the
        process is simpler. It is a three stage process classifying BIAS, FLAT
        and OBJECT datatype. The data is packed in groups that are
        pandas.DataFrame objects.

        """

        # bias data group
        date_obs_list = self.file_collection['date-obs'].tolist()

        afternoon_twilight, morning_twilight, sun_set, sun_rise = \
            get_twilight_time(date_obs=date_obs_list)

        self.data_container.set_sun_times(sun_set=sun_set,
                                          sun_rise=sun_rise)

        self.data_container.set_twilight_times(evening=afternoon_twilight,
                                               morning=morning_twilight)

        bias_group = self.file_collection[
            self.file_collection.obstype == 'BIAS'] # .tolist()

        if len(bias_group) > 2:

            bias_confs = bias_group.groupby(
                ['gain',
                 'rdnoise',
                 'radeg',
                 'decdeg']).size().reset_index().rename(columns={0: 'count'})

            for i in bias_confs.index:

                bias_group = bias_group[
                    ((bias_group['gain'] == bias_confs.iloc[i]['gain']) &
                    (bias_group['rdnoise'] == bias_confs.iloc[i]['rdnoise']) &
                    (bias_group['radeg'] == bias_confs.iloc[i]['radeg']) &
                    (bias_group['decdeg'] == bias_confs.iloc[i]['decdeg']))]

                self.data_container.add_bias(bias_group)
        else:
            log.error('Not enough bias images.')

        # flats separation
        flat_data = self.file_collection[self.file_collection.obstype == 'FLAT']

        # confs stands for configurations
        confs = flat_data.groupby(
            ['object',
             'filter']).size().reset_index().rename(columns={0: 'count'})

        for i in confs.index:

            flat_group = flat_data[
                ((flat_data['object'] == confs.iloc[i]['object']) &
                (flat_data['filter'] == confs.iloc[i]['filter']))]

            self.data_container.add_day_flats(flat_group)

        # science data separation
        science_data = self.file_collection[
            self.file_collection.obstype == 'OBJECT']

        # confs stands for configurations
        confs = science_data.groupby(
            ['object',
             'filter']).size().reset_index().rename(columns={0: 'count'})

        for i in confs.index:

            science_group = science_data[
                ((science_data['object'] == confs.iloc[i]['object']) &
                 (science_data['filter'] == confs.iloc[i]['filter']))]

            self.data_container.add_data_group(science_group)


class Night(object):
    """This class is designed to be the organized data container. It doesn't
    store image data but list of pandas.DataFrame objects. Also it stores
    critical variables such as sunrise and sunset times.

    """

    def __init__(self, path, instrument, technique):
        """Initializes all the variables for the class

        Args:
            path (str): Full path to the directory where raw data is located
            instrument (str): 'Red' or 'Blue' stating whether the data was taken
            using the Red or Blue Goodman Camera.
            technique (str): 'Spectroscopy' or 'Imaging' stating what kind of
            data was taken.
        """

        self.full_path = path
        self.instrument = instrument
        self.technique = technique
        self.is_empty = True
        self.bias = None
        self.day_flats = None
        self.dome_flats = None
        self.sky_flats = None
        self.data_groups = None
        self.sun_set_time = None
        self.sun_rise_time = None
        self.evening_twilight = None
        self.morning_twilight = None

    def add_bias(self, bias_group):
        """Adds a bias group

        Args:
            bias_group (pandas.DataFrame): Contains a set of keyword values of
            grouped image metadata

        """

        if len(bias_group) < 2:
            if self.technique == 'Imaging':

                log.error('Imaging mode needs BIAS to work properly. '
                          'Go find some.')

            else:
                log.warning('BIAS are needed for optimal results.')
        else:
            if self.bias is None:
                self.bias = [bias_group]
            else:
                self.bias.append(bias_group)
        if self.bias is not None:
            self.is_empty = False

    def add_day_flats(self, day_flats):
        """"Adds a daytime flat group

        Args:
            day_flats (pandas.DataFrame): Contains a set of keyword values of
            grouped image metadata

        """

        if self.day_flats is None:
            self.day_flats = [day_flats]
        else:
            self.day_flats.append(day_flats)
        if self.day_flats is not None:
            self.is_empty = False

    def add_data_group(self, data_group):
        """Adds a data group

        Args:
            data_group (pandas.DataFrame): Contains a set of keyword values of
            grouped image metadata

        """

        if self.data_groups is None:
            self.data_groups = [data_group]
        else:
            self.data_groups.append(data_group)
        if self.data_groups is not None:
            self.is_empty = False

    def set_sun_times(self, sun_set, sun_rise):
        """Sets values for sunset and sunrise

        Args:
            sun_set (str): Sun set time in the format 'YYYY-MM-DDTHH:MM:SS.SS'
            sun_rise (str):Sun rise time in the format 'YYYY-MM-DDTHH:MM:SS.SS'

        """

        self.sun_set_time = sun_set
        self.sun_rise_time = sun_rise

    def set_twilight_times(self, evening, morning):
        """Sets values for evening and morning twilight

        Args:
            evening (str): Evening twilight time in the format
            'YYYY-MM-DDTHH:MM:SS.SS'
            morning (str): Morning twilight time in the format
            'YYYY-MM-DDTHH:MM:SS.SS'

        """

        self.evening_twilight = evening
        self.morning_twilight = morning





