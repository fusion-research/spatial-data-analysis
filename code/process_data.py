import pandas as pd
import numpy as np
import pickle
import os
import glob
import datetime
import calendar
from pandas.tseries.holiday import USFederalHolidayCalendar
from collections import defaultdict


def load_data(data_path, load_paths, month_year_start, month_year_end, 
              day_start=None, day_end=None, verbose=False):
    """Process files with load data for block-faces to be used for further analysis.
    
    :param data_path: Path to directory containing blockface_locs.p and block_info.csv
    :param load_paths: Path to directory containing load data for block-faces
    or list of paths to directories containing load data for block-faces.
    :param month_year_start: Tuple of the integer month (1-12) and integer year to begin using data.
    :param month_end_start: Tuple of the integer month (1-12) and integer year to end using data.
    :param day_start: Integer day to begin using data corresponding to the start month and year.
    :param day_end: Integer day to end using data corresponding to the end month and year.
    :param verbose: Bool indicator of whether to print info about blocks that are skipped.

    :return element_keys: List containing the keys of block-faces with load data.
    :return avg_loads: Numpy array where each row is the load data for a block-face
    and each column corresponds to a day of week and hour.
    :return gps_loc: Numpy array with each row containing the lat, long pair
    midpoints for a block-face.
    :return park_data: Multi-index DataFrame containing datetimes in the first
    level index and block-face keys in the second level index. Values include
    the corresponding loads.
    :return idx_to_day_hour: Dictionary of column in avg_loads to (day, hour) pair.
    :return day_hour_to_idx: Dictionary of (day, hour) pair to column in avg_loads.
    """
    
    # Load file containing GPS coordinates for blockfaces.
    with open(os.path.join(data_path, 'blockface_locs.p'), 'rb') as f:
        locations = pickle.load(f)
    
    # Load sheet containing blockface info about blockface operating times.
    block_info = pd.read_csv(os.path.join(data_path, 'block_info.csv'))
    keep_columns = ['ElementKey', 'PeakHourStart1', 'PeakHourEnd1', 
                    'PeakHourStart2', 'PeakHourEnd2', 'PeakHourStart3', 
                    'PeakHourEnd3', 'EffectiveStartDate', 'EffectiveEndDate']
    block_info = block_info[keep_columns]
    
    # Converting to datetime format for processing.
    for col in keep_columns:
        if 'Hour' in col:
            block_info.loc[:, col] = pd.to_datetime(block_info[col]).dt.time
        elif 'Date' in col:
            block_info.loc[:, col] = pd.to_datetime(block_info[col])
        else:
            pass
    
    # Loading holiday information for when paid parking is not available.
    cal = USFederalHolidayCalendar()
    holidays = cal.holidays(start='2012-01-01', end=datetime.datetime.now().date()).to_pydatetime()
    holidays = [hol.date() for hol in holidays]

    # Getting starting and ending date to keep data for.
    if day_start == None:
        day_start = 1
    if day_end == None:
        day_end = calendar.monthrange(month_year_end[1], month_year_end[0])[1]

    date_start = datetime.date(month_year_start[1], month_year_start[0], day_start)
    date_end = datetime.date(month_year_end[1], month_year_end[0], day_end)

    avg_loads = []
    gps_loc = []
    element_keys = []
    park_data = {}
    
    if isinstance(load_paths, list):
        pass
    else:
        load_paths = [load_paths]

    for load_path in load_paths:
        for fi in sorted(glob.glob(load_path + os.sep + '*.csv'), key=lambda fi: int(fi.split(os.sep)[-1].split('.')[0])):
            key = int(fi.split(os.sep)[-1].split('.')[0])

            block_data = pd.read_csv(fi, names=['Datetime', 'Load'])

            block_data['Datetime'] = pd.to_datetime(block_data['Datetime'])
            block_data.sort_values(by='Datetime', inplace=True)

            # Dropping days where the supply was 0 for this blockface.
            block_data.dropna(inplace=True)

            block_data['Date'] = block_data['Datetime'].dt.date
            block_data['Time'] = block_data['Datetime'].dt.time
            block_data['Day'] = block_data['Datetime'].dt.weekday
            block_data['Hour'] = block_data['Datetime'].dt.hour
            block_data['Minute'] = block_data['Datetime'].dt.minute

            # Keeping the data in the specified date range.
            block_data = block_data.loc[(block_data['Date'] >= date_start) & (block_data['Date'] <= date_end)]

            # Getting rid of Sunday since there is no paid parking.
            block_data = block_data.loc[block_data['Day'] != 6]

            # Dropping the days where the total parking is 0 because of holidays.
            block_data = block_data.loc[~block_data['Date'].isin(holidays)]
            block_data.reset_index(inplace=True, drop=True)

            # Clipping the loads to be no higher than 1.5
            block_data['Load'] = block_data['Load'].clip_upper(1.5)

            # If block contains no data, skip it.
            if len(block_data) == 0:
                if verbose:
                    print('Skipping block %d because the supply is always 0.' % key)
                continue

            # If the block always has 0 occupancy, skip it.
            if len(block_data.loc[block_data['Load'] != 0]) == 0:
                if verbose:
                    print('Skipping block %d because the occupancy is always 0.' % key)
                continue

            # Get GPS midpoint for block-face and skip if no information for it.
            if key in locations:
                curr_block = locations[key]

                lat1, lat2 = curr_block[1], curr_block[-2]
                lon1, lon2 = curr_block[0], curr_block[-3]

                mid_lat = (lat1 + lat2)/2.
                mid_long = (lon1 + lon2)/2.
                gps_loc.append([mid_lat, mid_long])
            else:
                if verbose:
                    print('Skipping block %d because it was not found in locations.' % key)
                continue

            # Getting block-face info for the current key about hours of operation.
            curr_block_info = block_info.loc[block_info['ElementKey'] == key]

            # Filling times where paid parking is not allowed for the block with nan.
            for index, row in curr_block_info.iterrows():
                row_null = row.isnull()

                if not row_null['PeakHourStart1'] and not row_null['PeakHourStart2'] and not row_null['PeakHourStart3']:
                    continue

                if not row_null['EffectiveEndDate']:
                    row['EffectiveEndDate'] += datetime.timedelta(hours=23, minutes=59, seconds=59)

                if not row_null['PeakHourStart1']:

                    start1 = pd.Series([datetime.datetime.combine(block_data.loc[i, 'Date'], row['PeakHourStart1']) for i in xrange(len(block_data))])
                    end1 = pd.Series([datetime.datetime.combine(block_data.loc[i, 'Date'], row['PeakHourEnd1']) for i in xrange(len(block_data))])

                    if row_null['EffectiveEndDate']:
                        mask1 = ((row['EffectiveStartDate'] <= block_data['Datetime'])
                                 & (start1 <= block_data['Datetime']) 
                                 & (end1 > block_data['Datetime'])
                                 & (block_data['Day'] != 5))
                    else:
                        mask1 = ((row['EffectiveStartDate'] <= block_data['Datetime']) 
                                 & (row['EffectiveEndDate'] >= block_data['Datetime'])
                                 & (start1 <= block_data['Datetime']) 
                                 & (end1 > block_data['Datetime'])
                                 & (block_data['Day'] != 5))

                    block_data.loc[mask1, 'Load'] = np.nan    

                if not row_null['PeakHourStart2']:

                    start2 = pd.Series([datetime.datetime.combine(block_data.loc[i, 'Date'], row['PeakHourStart2']) for i in xrange(len(block_data))])
                    end2 = pd.Series([datetime.datetime.combine(block_data.loc[i, 'Date'], row['PeakHourEnd2']) for i in xrange(len(block_data))])

                    if row_null['EffectiveEndDate']:
                        mask2 = ((row['EffectiveStartDate'] <= block_data['Datetime'])
                                & (start2 <= block_data['Datetime']) 
                                & (end2 > block_data['Datetime'])
                                & (block_data['Day'] != 5))
                    else:
                        mask2 = ((row['EffectiveStartDate'] <= block_data['Datetime']) 
                                 & (row['EffectiveEndDate'] >= block_data['Datetime'])
                                 & (start2 <= block_data['Datetime']) 
                                 & (end2 > block_data['Datetime'])
                                 & (block_data['Day'] != 5))

                    block_data.loc[mask2, 'Load'] = np.nan  

                if not row_null['PeakHourStart3']:

                    start3 = pd.Series([datetime.datetime.combine(block_data.loc[i, 'Date'], row['PeakHourStart3'])
                                        for i in xrange(len(block_data))])
                    end3 = pd.Series([datetime.datetime.combine(block_data.loc[i, 'Date'], row['PeakHourEnd3'])
                                      for i in xrange(len(block_data))])

                    if row_null['EffectiveEndDate']:
                        mask3 = ((row['EffectiveStartDate'] <= block_data['Datetime'])
                                 & (start3 <= block_data['Datetime']) 
                                 & (end3 > block_data['Datetime'])
                                 & (block_data['Day'] != 5))
                    else:
                        mask3 = ((row['EffectiveStartDate'] <= block_data['Datetime']) 
                                 & (row['EffectiveEndDate'] >= block_data['Datetime'])
                                 & (start3 <= block_data['Datetime']) 
                                 & (end3 > block_data['Datetime'])
                                 & (block_data['Day'] != 5))

                    block_data.loc[mask3, 'Load'] = np.nan   

            # Getting the average load for each hour of the week for the block.
            avg_load = block_data.groupby(['Day', 'Hour'])['Load'].mean().values.reshape((1,-1))

            # If there is not data skip it.
            if avg_load.shape != (1, 72):
                gps_loc.pop()
                continue

            avg_loads.append(avg_load)
            element_keys.append(key)
            park_data[key] = block_data
    
    # Each row has load and GPS locations for a block. Ordered as in element_keys.
    avg_loads = np.vstack((avg_loads))
    gps_loc = np.vstack((gps_loc))

    index = park_data[park_data.keys()[0]].groupby(['Day', 'Hour']).sum().index

    days = index.get_level_values(0).unique().values
    days = np.sort(days)

    hours = index.get_level_values(1).unique().values
    hours = np.sort(hours)

    idx_to_day_hour = {i*len(hours) + j:(days[i], hours[j]) for i in range(len(days)) 
                                                            for j in range(len(hours))}
    day_hour_to_idx = {v:k for k,v in idx_to_day_hour.items()}
    
    for key in park_data:
        park_data[key] = park_data[key].set_index('Datetime')

    # Merging the dataframes into multi-index dataframe.
    park_data = pd.concat(park_data.values(), keys=park_data.keys())

    park_data.index.names = ['ID', 'Datetime']

    # Making the first index the date, and the second the element key, sorted by date.
    park_data = park_data.swaplevel(0, 1).sort_index()

    return element_keys, avg_loads, gps_loc, park_data, idx_to_day_hour, day_hour_to_idx


def get_price_changes(area, data_path):
    """Find price or time changes for blockfaces in a neighborhood.

    :param area: String of neighborhood to find changes for.
    :param data_path: Path to directory containing block_info.csv

    :return price_changes: Default dictionary with keys being a tuple of dates, 
    where the first date is when a price changed and the second date being when
    that price started. The values are a tuple of the block key and an array of 
    the price changes at each time interval. These are relative. A negative 
    value would mean price decreased by that amount after the first date in the key. 

    :return time_changes: Default dictionary with keys being a tuple of dates, 
    where the first date is when the start or end time of paid parking changed 
    and the second date being when that time interval started. The values are a 
    tuple of the block key, the previous times of paid parking, and the new times
    of paid parking. 
    """

    block_info = pd.read_csv(os.path.join(data_path, 'block_info.csv'))
    area = block_info.loc[block_info['PaidParkingArea'] == area]

    price_changes = defaultdict(list)
    time_changes = defaultdict(list)

    for key in area['ElementKey'].unique():
        block = area.loc[area['ElementKey'] == key]
        block = block.dropna(subset=['WeekdayRate1'])
        block = block.sort_values(by='EffectiveStartDate')

        prices = block.loc[:, ['WeekdayRate1', 'WeekdayRate2', 'WeekdayRate3', 
                               'SaturdayRate1', 'SaturdayRate2', 'SaturdayRate3']].values
        times = block.loc[:, ['StartTimeWeekday', 'EndTimeWeekday', 
                              'StartTimeSaturday', 'EndTimeSaturday']].values
        dates = block.loc[:, ['EffectiveStartDate', 'EffectiveEndDate']].values

        for i in xrange(len(block)-1):
            if not np.array_equal(prices[i], prices[i+1]):
                price_changes[(dates[i+1,0], dates[i,0])].append((key, prices[i]-prices[i+1]))
            if not np.array_equal(times[i], times[i+1]):
                time_changes[(dates[i+1,0], dates[i,0])].append((key, times[i], times[i+1]))
                
    return price_changes, time_changes