import numpy as np
from sklearn.preprocessing import MinMaxScaler
from sklearn import mixture
import moran_auto
import itertools
import multiprocessing
import functools
import warnings
warnings.filterwarnings('ignore')


def locational_demand_analysis(park_data, gps_loc, k):
    """Find GMM prediction error at each day of the week and time of day.

    This function also finds the spatial autocorrelation characteristics using 
    Moran's I with two types of weight matrices and gets the centroids 
    at each fit of the mixture model for each day of the week and time of the day.
    
    :param park_data: Multi-index DataFrame containing dates and blockface key
    indexes and the corresponding loads, hour, and day.
    :param gps_loc: Numpy array with each row containing the GPS coordinates of 
    each blockface ordered the same as in park_data.
    :param N: Integer number of samples (locations).

    :return results: List of tuples with each tuple containing the day of week 
    as an integer, integer hour of the day, prediction accuracy, and list of 
    numpy arrays of the GPS coordinates of the centroids of the cluster for each
    fit.
    """

    days = sorted(park_data['Day'].unique())
    hours = sorted(park_data['Hour'].unique())

    times = list(itertools.product(days, hours))

    pool = multiprocessing.Pool()

    func = functools.partial(GMM, park_data, gps_loc, times, k)
    results = pool.map(func, range(len(times)))

    pool.close()
    pool.join()

    return results


def GMM(park_data, gps_loc, times, k, iteration):
    """Finding the GMM prediction error for a day and hour combination.

    This function also finds spatial autocorrelation characteristics using 
    Moran's I with two types of weight matrices and gets the centroids 
    at each fit of the mixture model.
    
    :param park_data: Multi-index DataFrame containing dates and blockface key
    indexes and the corresponding loads, hour, and day.
    :param gps_loc: Numpy array with each row containing the GPS coordinates of 
    each blockface ordered the same as in park_data.
    :param times: List of tuples, with each tuple containing day and hour pair.
    :param N: Integer number of samples (locations).
    :param iter: Integer iteration number of the multiprocessing.

    :return day: Integer day of week.
    :return hour: Integer hour of the day. 

    :return time_avg_accuracy: Float of the accuracy percentage of the mixture
    model predictions (a test point is correct if it stays in the same component),
    averaged over fitting a model on a date, testing on all others, averaging 
    over the testing accuracies and then averaging over all these averages for 
    each time a model is fit on a date.

    :return morans_mixture: List of tuples for each date in the training set 
    with each tuple containing the Moran I value, Moran expectation value, Moran 
    variance, Moran z score, Moran one sided p value, and Moran two sided p 
    value using the connections of the mixture components as the weight matrix.

    :return morans_adjacent: List of tuples for each date in the training set 
    with each tuple containing the Moran I value, Moran expectation value, Moran 
    variance, Moran z score, Moran one sided p value, and Moran two sided p 
    value using the adjacent connections as the weight matrix.

    :return centers: List of numpy arrays of the centroids of each fit.
    """

    mask_small = False

    time = times[iteration]
    day = time[0]
    hour = time[1]

    data_df = park_data.loc[(park_data['Day'] == day) & (park_data['Hour'] == hour)]
    block_keys = sorted(data_df.index.get_level_values(1).unique().tolist())

    average_accuracies = []
    centers = [] 
    morans_mixture = [] 
    morans_area = []
    morans_adjacent = []  

    for train_time in data_df.index.get_level_values(0).unique().tolist():
        train_data = data_df.xs(train_time, level=0)

        if mask_small:
            train_data.loc[(train_data['Load'] <= .05), 'Load'] = np.nan

        train_data = train_data.dropna()

        N = len(train_data)

        train_active_index = train_data.index.tolist()
        train_mask = [block_keys.index(train_active_index[i]) for i in xrange(len(train_active_index))]  
        train_to_label_map = {train_active_index[i]: i for i in xrange(len(train_active_index))}

        train_loads = train_data['Load'].values.reshape((-1, 1))

        train = np.hstack((train_loads, gps_loc[train_mask]))

        # Saving the scaling so it can be applied to the test set as well.
        scaler = MinMaxScaler().fit(train)
        train = scaler.transform(train)

        gmm = mixture.GaussianMixture(n_init=10, n_components=4, 
                                      covariance_type='diag').fit(train)

        # Scaling the mean and covariances back to GPS coordinates.
        means = np.vstack(([(mean[1:] - scaler.min_[1:])/(scaler.scale_[1:]) for mean in gmm.means_]))
        covs = np.dstack(([np.diag((cov[1:])/(scaler.scale_[1:]**2)) for cov in gmm.covariances_])).T

        centers.append(means)

        train_labels = gmm.predict(train)

        # Getting spatial correlation statistics for Moran's I using mixture component connections.
        weights = moran_auto.get_mixture_weights(train_labels, N)        
        I = moran_auto.moran_mixture(train_loads[:, 0], train_labels, N)
        expectation = moran_auto.moran_expectation(N)
        variance = moran_auto.moran_variance(train_loads[:, 0], weights, N)
        z_score = moran_auto.z_score(I, expectation, variance)
        p_one_sided, p_two_sided = moran_auto.p_value(z_score)

        morans_mixture.append([I, expectation, variance, z_score, p_one_sided, p_two_sided])

        # Getting spatial correlation statistics for Moran's I using mixture paid area connections.
        weights = moran_auto.get_area_weights(train_active_index, N)        
        I = moran_auto.moran_area(train_loads[:, 0], train_active_index, N)
        expectation = moran_auto.moran_expectation(N)
        variance = moran_auto.moran_variance(train_loads[:, 0], weights, N)
        z_score = moran_auto.z_score(I, expectation, variance)
        p_one_sided, p_two_sided = moran_auto.p_value(z_score)

        morans_area.append([I, expectation, variance, z_score, p_one_sided, p_two_sided])

        # Getting spatial correlation statistics for Moran's I using adjacent weight matrix.
        weights = moran_auto.get_adjacent_weights(gps_loc[train_mask], N)        
        I = moran_auto.moran_adjacent(train_loads[:, 0], gps_loc[train_mask], N, k)
        expectation = moran_auto.moran_expectation(N)
        variance = moran_auto.moran_variance(train_loads[:, 0], weights, N)
        z_score = moran_auto.z_score(I, expectation, variance)
        p_one_sided, p_two_sided = moran_auto.p_value(z_score)

        morans_adjacent.append([I, expectation, variance, z_score, p_one_sided, p_two_sided])

        accuracies = []

        # For each other day of data, predict using model that was fit.
        for test_time in data_df.index.get_level_values(0).unique().tolist():

            # Skipping predicting on the time that was trained on.
            if test_time == train_time:
                continue

            test_data = data_df.xs(test_time, level=0)

            if mask_small:
                test_data.loc[test_data['Load'] <= .05, 'Load'] = np.nan

            test_data = test_data.dropna()

            test_data = test_data.loc[test_data.index.isin(train_active_index)]

            test_active_index = test_data.index.tolist()
            test_mask = [block_keys.index(test_active_index[i]) for i in xrange(len(test_active_index))]  

            test_loads = test_data['Load'].values.reshape((-1, 1))

            test = np.hstack((test_loads, gps_loc[test_mask]))

            test = scaler.transform(test)

            # Assigning labels for the test points using the model that was trained. 
            test_labels = gmm.predict(test)

            correct = 0
            incorrect = 0

            for i in xrange(len(test_labels)):
                key = test_active_index[i]
                idx = train_to_label_map[key]

                if test_labels[i] == train_labels[idx]:
                    correct += 1
                else:
                    incorrect += 1

            # A prediction is deemed correct if a block keeps the same label.
            accuracy = correct/float(correct + incorrect)
            accuracies.append(accuracy)

            # Getting average prediction accuracy over all test sets.
        average_accuracies.append(np.array(accuracies).mean())

    # Average error for the particular day and hour combination.
    time_avg_error = round(100.0 - np.array(average_accuracies).mean() * 100, 2)

    return day, hour, time_avg_error, morans_mixture, morans_area, morans_adjacent, centers