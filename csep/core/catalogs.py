import numpy
import pandas
import datetime
import operator
import pyproj

# CSEP Imports
import csep
from csep.utils.time import epoch_time_to_utc_datetime, timedelta_from_years, datetime_to_utc_epoch, strptime_to_utc_datetime
from csep.utils.comcat import search
from csep.utils.stats import min_or_none, max_or_none
from csep.utils.calc import discretize
from csep.utils.comcat import SummaryEvent
from csep.core.repositories import Repository, repo_builder
from csep.core.exceptions import CSEPSchedulerException
from csep.utils.spatial import bin_catalog_spatial_counts, bin1d_vec
from csep.utils.constants import CSEP_MW_BINS


class AbstractBaseCatalog:
    """
    Base class for CSEP2 catalogs.

    Todo:
        Come up with idea on how to manage the region of a catalog.
        Would be used for filtering or binning. shapely, geopandas for spatial and DataFrame for temporal.
    """
    dtype = numpy.dtype([])

    def __init__(self, filename=None, catalog=None, catalog_id=None, format=None, name=None, region=None, compute_stats=False,
                 min_magnitude=None, max_magnitude=None,
                 min_latitude=None, max_latitude=None,
                 min_longitude=None, max_longitude=None,
                 start_time=None, end_time=None):

        self.filename = filename
        self.catalog_id = catalog_id
        self.format = format
        self.name = name
        self.region = region
        self.compute_stats = compute_stats

        # cleans the catalog to set as ndarray, see setter.
        self.catalog = catalog

        # class attributes that are not settable from constructor (adding here for readability)
        self.mfd = None

        # set these values from initially
        self.max_magnitude = max_magnitude
        self.min_magnitude = min_magnitude
        self.min_latitude = min_latitude
        self.max_latitude = max_latitude
        self.min_longitude = min_longitude
        self.max_longitude = max_longitude
        self.start_time = start_time
        self.end_time = end_time

        # use user defined stats if entered into catalog
        try:
            if catalog is not None and self.compute_stats:
                self.update_catalog_stats()
        except (AttributeError, NotImplementedError):
            print('Warning: could not parse catalog statistics by reading catalog. get_magnitudes(), get_latitudes() and get_longitudes() ' +
                  'must be implemented and bound to calling class! Reverting to old values.')

    def __str__(self):
        s=f'''
        Name: {self.name}

        Start Date: {self.start_time}
        End Date: {self.end_time}

        Latitude: ({self.min_latitude}, {self.max_latitude})
        Longitude: ({self.min_longitude}, {self.max_longitude})

        Min Mw: {self.min_magnitude}
        Max Mw: {self.max_magnitude}
        
        Event Count: {self.event_count}
        '''
        return s

    def to_dict(self):
        """
        Serializes class to json dictionary.

        Returns:
            catalog as dict

        """
        excluded = ['mfd', '_catalog']
        out = {}
        for k, v in self.__dict__.items():
            if not callable(v) and k not in excluded:
                if hasattr(v, 'to_dict'):
                    new_v = v.to_dict()
                else:
                    new_v = v
                if k.startswith('_'):
                    out[k[1:]] = new_v
                else:
                    out[k] = new_v
        out['catalog'] = []
        for line in self.catalog.tolist():
            new_line=[]
            for item in line:
                try:
                    item = item.decode('utf-8')
                except:
                    pass
                finally:
                    new_line.append(item)        
            out['catalog'].append(new_line)
        return out

    @property
    def event_count(self):
        return self.get_number_of_events()

    @classmethod
    def from_dict(cls, adict):
        raise NotImplementedError

    @classmethod
    def from_dataframe(cls, df, **kwargs):
        """
        Creates catalog from dataframe. Dataframe must have columns that are equivalent to whatever fields
        the catalog expects.

        For example:

                cat = CSEPCatalog()
                df = cat.get_dataframe()
                new_cat = CSEPCatalog.from_dataframe(df)
                cat == new_cat

        Args:
            df (pandas.DataFrame): pandas dataframe
            **kwargs:

        Returns:
            Catalog

        """

        catalog_id = None
        try:
            catalog_id = df['catalog_id'].iloc[0]
        except KeyError:
            print('Warning: Unable to parse catalog_id, setting to default value')

        col_list = list(cls.dtype.names)
        # we want this to be a structured array not a record array
        catalog = numpy.ascontiguousarray(df[col_list].to_records(index=False), dtype=cls.dtype)
        out_cls = cls(catalog=catalog, catalog_id=catalog_id, **kwargs)
        return out_cls

    @property
    def catalog(self):
        return self._catalog

    @catalog.setter
    def catalog(self, val):
        """
        Ensures that catalogs with formats not numpy arrray are treated as numpy.array

        Note:
            This requires that catalog classes implement the self._get_catalog_as_ndarray() function.
            This function should return structured numpy.ndarray.
            Catalog will remain None, if assigned that way in constructor.
        """
        self._catalog = val
        if self._catalog is not None:
            self._catalog = self._get_catalog_as_ndarray()
            # ensure that people are behaving, somewhat non-pythonic but needed
            if not isinstance(self._catalog, numpy.ndarray):
                raise ValueError("Error: Catalog must be numpy.ndarray! Ensure that self._get_catalog_as_ndarray()" +
                                 " returns an ndarray")
        if self.compute_stats:
            self.update_catalog_stats()

    @classmethod
    def load_catalogs(cls, filename=None, **kwargs):
        """
        Generator function to handle loading a stochastic event set.
        """
        raise NotImplementedError('load_catalogs must be overwritten in child classes')

    def write_catalog(self, binary=True):
        """
        Write catalog in bespoke format. For interoperability, CSEPCatalog classes should be used.
        But we don't want to force the user to use a CSEP catalog if they are working with their own format.
        Each model might need to implement a custom reader if the file formats are different.

        Interally, catalogs should implement some method to convert them into a pandas DataFrame.
        """
        raise NotImplementedError('write_catalog not implemented.')

    def get_dataframe(self, with_datetime=False):
        """
        Returns pandas Dataframe describing the catalog. Explicitly casts to pandas DataFrame.

        Note:
            The dataframe will be in the format of the original catalog. If you require that the
            dataframe be in the CSEP ZMAP format, you must explicitly convert the catalog.

        Returns:
            (pandas.DataFrame): This function must return a pandas DataFrame

        Raises:
            ValueError: If self._catalog cannot be passed to pandas.DataFrame constructor, this function
                        must be overridden in the child class.
        """
        df = pandas.DataFrame(self.catalog)
        df['counts'] = 1
        df['catalog_id'] = self.catalog_id
        if with_datetime:
            df['datetime'] = df['origin_time'].map(epoch_time_to_utc_datetime)
            df.index = df['datetime']
        # queries the region for the index of each event
        if self.region is not None:
            df['region_id'] = self.region.get_index_of(self.get_longitudes(), self.get_latitudes())
        # bin magnitudes
        df['mag_id'] = self.get_mag_id(CSEP_MW_BINS)
        # set index as datetime
        return df

    def get_mag_id(self, mag_bins):
        return bin1d_vec(self.get_magnitudes(), mag_bins)

    def get_number_of_events(self):
        """
        Compute the number of events from a catalog by checking its length.

        :returns: number of events in catalog, zero if catalog is None
        """
        if self.catalog is not None:
            return self.catalog.shape[0]
        else:
            return 0

    def get_epoch_times(self):
        """
        Returns the datetime of the event as the UTC epoch time (aka unix timestamp)
        """
        raise NotImplementedError('get_epoch_times() must be implemented!')

    def get_cumulative_number_of_events(self):
        """
        Returns the cumulative number of events in the catalog. Primarily used for plotting purposes.
        Defined in the base class because all catalogs should be iterable.

        Returns:
            numpy.array: numpy array of the cumulative number of events, empty array if catalog is empty.
        """
        return numpy.cumsum(numpy.ones(self.event_count))

    def get_magnitudes(self):
        """
        Extend getters to implement conversion from specific catalog type to CSEP catalog.

# use user defined stats if entered into catalog
        :returns: list of magnitudes from catalog
        """
        raise NotImplementedError('get_magnitudes must be implemented by subclasses of AbstractBaseCatalog')

    def get_datetimes(self):
        """
        Returns datetime object from timestamp representation in catalog

        :returns: list of timestamps from events in catalog.
        """
        raise NotImplementedError('get_datetimes() not implemented!')

    def get_latitudes(self):
        """
        Returns:
            (numpy.array): latitude
        """
        raise NotImplementedError('get_latitudes() not implemented!')

    def get_longitudes(self):
        """
        Returns:
            (numpy.array): longitudes
        """
        raise NotImplementedError('get_longitudes() not implemented!')

    def get_inter_event_times(self, scale=1000):
        """

        Args:
            scale (int): scales epoch times to another unit. default is seconds

        Returns:
            inter_times (ndarray): inter event times

        """
        times = self.get_epoch_times()
        inter_times = numpy.diff(times)/scale
        return inter_times

    def get_inter_event_distances(self, ellps='WGS84'):
        """
        compute great circle distances between two points. requires pyproj

        Args:
            ellps (str): ellipsoid to compute distances. see pyproj.Geod for more info

        Returns:
            inter_dist (ndarray): ndarray of inter event distances in kilometers
        """
        geod = pyproj.Geod(ellps=ellps)
        lats = self.get_latitudes()
        lons = self.get_longitudes()
        # in-case pyproj doesn't behave nicely all the time
        if self.get_number_of_events() == 0:
            return numpy.array([])
        _, _, dists = geod.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
        return dists

    def get_bvalue(self):
        """
        Estimates the b-value of a catalog using Eq. 3.10 from Marzocchi and Sandri (2003)

        Args:
            dmw: Discretization of magnitudes

        Returns:

        """
        if self.get_number_of_events() == 0:
            return None
        mws = discretize(self.get_magnitudes(), CSEP_MW_BINS)
        dmw = CSEP_MW_BINS[1] - CSEP_MW_BINS[0]
        # compute the p term from eq 3.10 in marzocchi and sandri [2003]
        def p():
            top = dmw
            bottom = numpy.mean(mws) - numpy.min(mws)
            # this might happen if all mags are the same, or 1 event in catalog
            if bottom == 0:
                return None
            return 1 + top / bottom
        bottom = numpy.log(10)*dmw
        p = p()
        if p is None:
            return None
        return 1.0 / bottom * numpy.log(p)

    def get_mfd(self, delta_mw=0.3, p_value=0.05):
        """
        TODO: Implement this using maximum-likelihood statistics

        Computes magnitude frequency distribution for catalog. MFD is computed by creating magnitude bins
        discretized by delta_mw.

        Requires that self.get_dataframe() is implemented in order to compute MFD.

        Args:
            delta_mw (float): Magnitude spacing for magnitude binning
            p_value (float): p_value for student's t-distribution

        Returns:
            (pandas.DataFrame): Magnitude Freq Distribution. Counts and regression statistics attached for plotting.
        """
        raise PendingDeprecationWarning

    def filter(self, statement, in_place=True):
        """
        Filters the catalog based on value.

        Args:
            statement (str): logical statement to evaluate, e.g., 'magnitude > 4.0'

        Returns:
            self: instance of AbstractBaseCatalog, so that this function can be chained.

        """
        operators = {'>': operator.gt,
                     '<': operator.lt,
                     '>=': operator.ge,
                     '<=': operator.le,
                     '==': operator.eq}
        name, oper, value = statement.split(' ')
        filtered = self.catalog[operators[oper](self.catalog[name], float(value))]
        # returns a copy of the array
        if in_place:
            self.catalog = filtered
            return self
        else:
            # make and return new object
            cls = self.__class__
            inst = cls(catalog=filtered, catalog_id=self.catalog_id, format=self.format, name=self.name, region=self.region)
            return inst

    def filter_spatial(self, region):
        """
        Removes events outside of the region. This is slow and should be used once. Typically for isoloate a region
        near the mainshock. This should not be used to create gridded style data sets.

        Args:
            region: interface (implements obj.contains())

        Returns:
            self

        """
        mask = region.get_masked(self.get_longitudes(), self.get_latitudes())
        # logical index uses opposite boolean values than masked arrays, confusing i know.
        filtered = self.catalog[~mask]
        self.catalog = filtered
        # update the region to the new region
        self.region = region
        # self._update_catalog_stats()
        return self

    def get_csep_format(self):
        """
        This method should be overwritten for catalog formats that do not adhere to the CSEP ZMAP catalog format. For
        those that do, this method will return the catalog as is.

        """
        raise NotImplementedError('_get_csep_format() not implemented.')

    def update_catalog_stats(self):
        # update min and max values
        self.min_magnitude = min_or_none(self.get_magnitudes())
        self.max_magnitude = max_or_none(self.get_magnitudes())
        self.min_latitude = min_or_none(self.get_latitudes())
        self.max_latitude = max_or_none(self.get_latitudes())
        self.min_longitude = min_or_none(self.get_longitudes())
        self.max_longitude = max_or_none(self.get_longitudes())
        self.start_time = epoch_time_to_utc_datetime(min_or_none(self.get_epoch_times()))
        self.end_time = epoch_time_to_utc_datetime(max_or_none(self.get_epoch_times()))

    def _get_catalog_as_ndarray(self):
        """
        This function must be implemented if the catalog is loaded in a bespoke format.
        This function will be called anytime that a catalog is assigned
        to self.catalog and is not of type ndarray.

        The structure of the ndarray does not matter, so long as the getters can be
        implemented correctly.

        Additionally, advanced catalog operations could be carried out using GeoDataFrames and
        DataFrames.
        """
        if isinstance(self.catalog, numpy.ndarray):
            return self.catalog
        n = len(self.catalog)
        catalog = numpy.array(n, dtype=self.dtype)
        # parsing for comcat SummaryEvent
        for i, event in self.catalog:
            catalog[i] = tuple(event)
        return catalog

    def gridded_event_counts(self):
        """
        This function is bad and should be broken up into multiple parts. In general, it works by circumscribing the
        polygons with a bounding box. Inside the bounding box is assumed to follow a regular Cartesian grid.

        We figure out the index of the polygons and create a map that relates the spatial coordinate in the
        Cartesian grid with with the polygon in region.

        Args:
            region: list of polygons

        Returns:
            outout: unnormalized event count in each bin, 1d ndarray where index corresponds to midpoints
            midpoints: midpoints of polygons in region
            cartesian: data embedded into a 2d map. can be used for quick plotting in python
        """
        # make sure region is specified with catalog
        if self.region is None:
            raise CSEPSchedulerException("Cannot create binned rates without region information.")
        output = csep.utils.spatial.bin_catalog_spatial_counts(self.get_longitudes(),
                                                               self.get_latitudes(),
                                                               len(self.region.polygons),
                                                               self.region.bitmask,
                                                               self.region.xs,
                                                               self.region.ys)
        return output

    def gridded_space_mag_counts(self):
        """
        This function is bad and should be broken up into multiple parts. In general, it works by circumscribing the
        polygons with a bounding box. Inside the bounding box is assumed to follow a regular Cartesian grid.

        We figure out the index of the polygons and create a map that relates the spatial coordinate in the
        Cartesian grid with with the polygon in region.

        Args:
            region: list of polygons

        Returns:
            outout: unnormalized event count in each bin, 1d ndarray where index corresponds to midpoints
            midpoints: midpoints of polygons in region
            cartesian: data embedded into a 2d map. can be used for quick plotting in python
        """

        # make sure region is specified with catalog
        if self.region is None:
            raise CSEPSchedulerException("Cannot create binned rates without region information.")
        output = csep.utils.spatial.bin_catalog_spatio_magnitude_counts(self.get_longitudes(),
                                                                        self.get_latitudes(),
                                                                        self.get_magnitudes(),
                                                                        len(self.region.polygons),
                                                                        self.region.bitmask,
                                                                        self.region.xs,
                                                                        self.region.ys)
        return output

    def binned_magnitude_counts(self, bins=CSEP_MW_BINS, retbins=False):
        out = numpy.zeros(len(bins))
        idx = bin1d_vec(self.get_magnitudes(), bins)
        numpy.add.at(out, idx, 1)
        if retbins:
            return (bins, out)
        else:
            return out


class CSEPCatalog(AbstractBaseCatalog):
    """
    Catalog stored in CSEP2 format. This catalog be used when operating within the CSEP2 software ecosystem.
    """
    # define representation for each event in catalog
    dtype = numpy.dtype([('longitude', numpy.float32),
                        ('latitude', numpy.float32),
                        ('year', numpy.int32),
                        ('month', numpy.int32),
                        ('day', numpy.int32),
                        ('magnitude', numpy.float32),
                        ('depth', numpy.float32),
                        ('hour', numpy.int32),
                        ('minute', numpy.int32),
                        ('second', numpy.int32)])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_longitudes(self):
        return self.catalog['longitude']

    def get_latitudes(self):
        return self.catalog['latitude']

    def get_magnitudes(self):
        """
        extend getters to implement conversion from specific catalog type to CSEP catalog.

        Returns:
            (numpy.array): magnitudes from catalog
        """
        return self.catalog['magnitude']

    def get_datetimes(self):
        """
        returns datetime object from timestamp representation in catalog

        :returns: list of timestamps from events in catalog.
        """
        datetimes = []
        for event in self.catalog:
            year = event['year']
            month = event['month']
            day = event['day']
            hour = event['hour']
            minute = event['minute']
            second = event['second']
            dt = datetime.datetime(year, month, day, hour=hour, minute=minute, second=second)
            datetimes.append(dt)
        return datetimes

    def get_epoch_times(self):
        dts = self.get_datetimes()
        return list(map(datetime_to_utc_epoch, dts))

    def get_csep_format(self):
        return self


class UCERF3Catalog(AbstractBaseCatalog):
    """
    Handles catalog type for stochastic event sets produced by UCERF3.

    :var header_dtype: numpy.dtype description of synthetic catalog header.
    :var event_dtype: numpy.dtype description of ucerf3 catalog format
    """
    # binary format of UCERF3 catalog
    header_dtype = numpy.dtype([("file_version", ">i2"), ("catalog_size", ">i4")])
    dtype = numpy.dtype([("rupture_id", ">i4"),
                         ("parent_id", ">i4"),
                         ("generation", ">i2"),
                         ("origin_time", ">i8"),
                         ("latitude", ">f8"),
                         ("longitude", ">f8"),
                         ("depth", ">f8"),
                         ("magnitude", ">f8"),
                         ("dist_to_parent", ">f8"),
                         ("erf_index", ">i4"),
                         ("fss_index", ">i4"),
                         ("grid_node_index", ">i4")])

    def __init__(self, **kwargs):
        # initialize parent constructor
        super().__init__(**kwargs)

    @classmethod
    def load_catalogs(cls, filename=None, filters=(), **kwargs):
        """
        Loads catalogs based on the merged binary file format of UCERF3. File format is described at
        https://scec.usc.edu/scecpedia/CSEP2_Storing_Stochastic_Event_Sets#Introduction.

        There is also the load_catalog method that will work on the individual binary output of the UCERF3-ETAS
        model.

        :param filename: filename of binary stochastic event set
        :type filename: string
        :returns: list of catalogs of type UCERF3Catalog
        """
        with open(filename, 'rb') as catalog_file:
            # parse 4byte header from merged file
            number_simulations_in_set = numpy.fromfile(catalog_file, dtype='>i4', count=1)[0]
            # load all catalogs from merged file
            for catalog_id in range(number_simulations_in_set):
                header = numpy.fromfile(catalog_file, dtype=cls.header_dtype, count=1)
                catalog_size = header['catalog_size'][0]
                # read catalog
                catalog = numpy.fromfile(catalog_file, dtype=cls.dtype, count=catalog_size)
                # add column that stores catalog_id in case we want to store in database
                u3_catalog = cls(filename=filename, catalog=catalog, catalog_id=catalog_id, **kwargs)
                # generator function, maybe apply filters here
                yield u3_catalog


    def get_datetimes(self):
        """
        Gets python datetime objects from time representation in catalog.

        Note:
            All times should be considered UTC time. If you are extending or working with this class make sure to
            ensure that datetime objects are not converted back to the local platform time.

        Returns:
            list: list of python datetime objects in the UTC timezone. one for each event in the catalog
        """
        datetimes = []
        for event in self.catalog:
            dt = epoch_time_to_utc_datetime(event['origin_time'])
            datetimes.append(dt)
        return datetimes

    def get_epoch_times(self):
        return self.catalog['origin_time']

    def get_magnitudes(self):
        """
        Returns array of magnitudes from the catalog.

        Returns:
            numpy.array: magnitudes of observed events in the catalog
        """
        return self.catalog['magnitude']

    def get_longitudes(self):
        return self.catalog['longitude']

    def get_latitudes(self):
        return self.catalog['latitude']

    def get_csep_format(self):
        n = len(self.catalog)
        # allocate array for csep catalog
        csep_catalog = numpy.zeros(n, dtype=CSEPCatalog.dtype)

        for i, event in enumerate(self.catalog):
            dt = epoch_time_to_utc_datetime(event['origin_time'])
            year = dt.year
            month = dt.month
            day = dt.day
            hour = dt.hour
            minute = dt.minute
            second = dt.second
            csep_catalog[i] = (event['longitude'],
                               event['latitude'],
                               year,
                               month,
                               day,
                               event['magnitude'],
                               event['depth'],
                               hour,
                               minute,
                               second)

        return CSEPCatalog(catalog=csep_catalog, catalog_id=self.catalog_id, filename=self.filename)


class ComcatCatalog(AbstractBaseCatalog):
    """
    Class handling retrieval of Comcat Catalogs.
    """
    dtype = numpy.dtype([('id', 'S256'),
                         ('origin_time', '<i8'),
                         ('latitude', '<f4'),
                         ('longitude','<f4'),
                         ('depth', '<f4'),
                         ('magnitude','<f4')])

    def __init__(self, catalog_id='Comcat', format='comcat', start_epoch=None, duration_in_years=None,
                 date_accessed=None, query=True, extra_comcat_params={}, **kwargs):

        # parent class constructor
        super().__init__(catalog_id=catalog_id, format=format, **kwargs)

        self.date_accessed = date_accessed
        # if made with no catalog object, load catalog on object creation
        if self.catalog is None and query:
            if self.start_time is None and start_epoch is None:
                self.log.warning("start_time and start_epoch must not be none to query comcat.")
                query = False
            else:
                self.start_time = self.start_time or epoch_time_to_utc_datetime(start_epoch)

            if self.end_time is None and duration_in_years is None:
                self.log.warning("and_time and duration_in_years must not be none.")
                query = False
            else:
                self.end_time = self.end_time or self.start_time + timedelta_from_years(duration_in_years)

            if query:
                if self.start_time < self.end_time:
                    self.query_comcat(extra_comcat_params)
                else:
                    self.log.warning("start_time must be less than end_time in order to query comcat servers.")

    @classmethod
    def from_dict(cls, adict):
        exclude = ['catalog', 'start_time', 'end_time', 'date_accessed']

        catalog = adict.get('catalog', None)
        start_time = adict.get('start_time', None)
        end_time = adict.get('end_time', None)
        date_accessed = adict.get('date_accessed', None)

        if start_time is not None:
            start_time=strptime_to_utc_datetime(start_time)

        if end_time is not None:
            end_time = strptime_to_utc_datetime(end_time)

        if date_accessed is not None:
            date_accessed = strptime_to_utc_datetime(date_accessed)

        out = cls(catalog=catalog,
                  start_time=start_time, end_time=end_time,
                  date_accessed=date_accessed)

        for k,v in out.__dict__.items():
            if k not in exclude:
                try:
                    setattr(out, k, adict[k])
                except Exception:
                    pass
        return out

    def query_comcat(self, extra_comcat_params={}):
        """
        The default parameters are given from the California testing region defined by the CSEP1 template files. starttime
        and endtime are exepcted to be datetime objects with the UTC timezone.
        Enough information needs to be provided in order to calculate a start date and end date.

        1) start_time and end_time
        2) start_time and duration_in_years
        3) epoch_time and end_time
        4) epoch_time and duration_in_years

        If start_time and start_epoch are both supplied, program will default to using start_time.
        If end_time and time_delta are both supplied, program will default to using end_time.

        This requires an internet connection and will fail if the script has no access to the server.

        Args:
            repo (Repository): repository object to load catalogs.
            extra_comcat_params (dict): pass additional parameters to libcomcat
        """

        # get eventlist from Comcat
        eventlist = search(minmagnitude=self.min_magnitude,
            minlatitude=self.min_latitude, maxlatitude=self.max_latitude,
            minlongitude=self.min_longitude, maxlongitude=self.max_longitude,
            starttime=self.start_time, endtime=self.end_time, **extra_comcat_params)

        # eventlist is converted to ndarray in _get_catalog_as_ndarray called from setter
        self.catalog = eventlist

        # update state because we just loaded a new catalog
        self.date_accessed = datetime.datetime.utcnow()

        if self.compute_stats:
            self.update_catalog_stats()

        return self

    @classmethod
    def load(cls, repo):
        """
        Returns new class object using the repository stored with the class. Maybe this should be a class
        method.

        """
        if isinstance(repo, Repository):
            out=repo.load(cls())
        elif type(repo) == dict:
            repo = repo_builder.create(repo['name'], repo)
            out=repo.load(cls())
        else:
            raise CSEPSchedulerException("Unable to load state. Repository must not be None.")
        return out

    def get_magnitudes(self):
        """
        Retrieves numpy.array of magnitudes from Comcat eventset.

        Returns:
            numpy.array: of magnitudes
        """
        return self.catalog['magnitude']

    def get_datetimes(self):
        """
        Returns datetime objects from catalog.

        Returns:
            (list): datetime.datetime objects
        """
        datetimes = []
        for event in self.catalog:
            datetimes.append(epoch_time_to_utc_datetime(event['origin_time']))
        return datetimes

    def get_longitudes(self):
        return self.catalog['longitude']

    def get_latitudes(self):
        return self.catalog['latitude']

    def get_epoch_times(self):
        return self.catalog['origin_time']

    def _get_catalog_as_ndarray(self):
        """
        Converts libcomcat eventlist into structured array.

        Note:
         Failure state exists if self.catalog is not bound
            to instance explicity.
        """
        # short-circuit
        if isinstance(self.catalog, numpy.ndarray):
            return self.catalog
        catalog_length = len(self.catalog)
        if catalog_length == 0:
            raise RuntimeError("Observed catalog is empty.")
        catalog = numpy.zeros(catalog_length, dtype=self.dtype)
        if isinstance(self.catalog[0], dict):
            for i, event in enumerate(self.catalog):
                catalog[i] = tuple(event)
        elif isinstance(self.catalog[0], SummaryEvent):
            for i, event in enumerate(self.catalog):
                catalog[i] = (event.id, datetime_to_utc_epoch(event.time),
                              event.latitude, event.longitude, event.depth, event.magnitude)
        else:
            raise TypeError("comcat catalog must be list of events with order:\n"
                            "id, epoch_time, latitude, longtiude, depth, magnitude. or \n"
                            "list of SummaryEvent type.")
        return catalog

    def get_csep_format(self):
        n = len(self.catalog)
        csep_catalog = numpy.zeros(n, dtype=CSEPCatalog.dtype)

        for i, event in enumerate(self.catalog):
            dt = epoch_time_to_utc_datetime(event['origin_time'])
            year = dt.year
            month = dt.month
            day = dt.day
            hour = dt.hour
            minute = dt.minute
            second = dt.second
            csep_catalog[i] = (event['longitude'],
                               event['latitude'],
                               year,
                               month,
                               day,
                               event['magnitude'],
                               event['depth'],
                               hour,
                               minute,
                               second)

        return CSEPCatalog(catalog=csep_catalog, catalog_id=self.catalog_id, filename=self.filename)


