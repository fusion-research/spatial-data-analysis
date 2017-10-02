import numpy as np
import os
import pandas as pd
from collections import defaultdict
import scipy.stats as st


def get_area_weights(train_active_index, N, data_path=os.path.join(os.getcwd(), '..', 'data')):
    """Get the weight matrix for Moran I by using the paid area connections.

    :param train_active_index: Numpy array of the active block-face keys.
    :param N: Integer number of samples (locations).
    :param data_path: File path to the paystation_info.csv.

    :return weights: Numpy array of the weight matrix.
    """

    weights = np.zeros((N, N))

    area_info = pd.read_csv(os.path.join(data_path, 'paystation_info.csv'))
    area_info = area_info[['ELMNTKEY', 'PAIDAREA', 'SUBAREA']]

    all_keys = area_info['ELMNTKEY'].unique().tolist()

    area_dict = defaultdict(list)
    key_dict = {}

    count = 0
    for key in train_active_index:

        if key in all_keys:
            neighborhood = area_info.loc[area_info['ELMNTKEY'] == key]['PAIDAREA'].unique().tolist()[0]
            subarea = area_info.loc[area_info['ELMNTKEY'] == key]['SUBAREA'].unique().tolist()[0]
            area = (neighborhood, subarea)   
        else:
            pass

        area_dict[area].append(count)
        key_dict[key] = area

        count += 1
    
    for i in xrange(N):
        weights[i, area_dict[key_dict[train_active_index[i]]]] = 1

    di = np.diag_indices(N)
    weights[di] = 0

    return weights


def moran_area(x, train_active_index, N):
    """Calculating the Moran I using the paid area weight matrix.

    :param x: Numpy array of the loads.
    :param train_active_index: Numpy array of the active block-face keys.
    :param N: Integer number of samples (locations).

    :return I: Float of Moran I.
    """

    weights = get_area_weights(train_active_index, N)

    W = weights.sum()
    z = x - x.mean()

    top = sum(weights[i, j]*z[i]*z[j] for i in xrange(N) for j in xrange(N)) 
    bottom = np.dot(z.T, z)

    I = (N/W) * top/bottom

    return I


def get_neighbor_weights(gps_loc, N, k):
    """Get the weight matrix for Moran I by using k nearest neighbor connections.

    :param gps_loc: Numpy array with each row containing the lat, long pair
    midpoints for a block-face.
    :param N: Integer number of samples (locations).
    :param k: Integer number of neighbors to use for the weighting matrix.

    :return weights: Numpy array of the weight matrix.
    """

    weights = np.zeros((N, N))

    for i in xrange(N):
        neighbors = np.vstack(sorted([(j, np.linalg.norm(gps_loc[i] - gps_loc[j])) for j in xrange(N)], key=lambda x: x[1])[1:k+1])[:, 0].astype('int')
        weights[i, neighbors] = 1

    return weights


def moran_neighbor(x, gps_loc, N, k):
    """Calculating the Moran I using the neighbor weight matrix.

    :param x: Numpy array of the loads.
    :param gps_loc: Numpy array with each row containing the lat, long pair
    midpoints for a block-face.
    :param N: Integer number of samples (locations).
    :param k: Integer number of neighbors to use for the weighting matrix.

    :return I: Float of Moran I.
    """

    weights = get_neighbor_weights(gps_loc, N, k)

    W = weights.sum()
    z = x - x.mean()

    top = sum(weights[i, j]*z[i]*z[j] for i in xrange(N) for j in xrange(N)) 
    bottom = np.dot(z.T, z)

    I = (N/W) * top/bottom

    return I


def get_mixture_weights(train_labels, N):
    """Calculate the Moran I weight matrix using the mixture connections.

    This function creates an weight matrix where each row represents a
    block-face and if a block-face is in the same mixture component as another
    it has a 1 in the corresponding column. The diagonal is 0.
    
    :param train_labels: Numpy array containing label for each data point.
    :param N: Integer number of samples (locations).

    :return weights: Numpy array of the weight matrix.
    """

    weights = np.zeros((N, N))

    for i in xrange(N):
        label = train_labels[i]
        matching = np.where(train_labels == label)[0].tolist()
        weights[i, matching] = 1

    di = np.diag_indices(N)
    weights[di] = 0

    return weights


def moran_mixture(x, train_labels, N):
    """Calculating the Moran I using the mixture model weight matrix.

    :param x: Numpy array of the loads.
    :param train_labels: Numpy array containing label for each data point.
    :param N: Integer number of samples.

    :return I: Float of Moran I.
    """

    weights = get_mixture_weights(train_labels, N)

    W = weights.sum()
    z = x - x.mean()

    top = sum(weights[i,j]*z[i]*z[j] for i in xrange(N) for j in xrange(N)) 
    bottom = np.dot(z.T, z)

    I = (N/W) * top/bottom

    return I


def moran_expectation(N):
    """Calculate the expected value of the Moran I.

    :param N: Integer number of samples (locations).

    :return expectation: Float of expectation of Moran I.
    """

    expectation = -1./(N - 1.)

    return expectation


def moran_variance(x, w, N):
    """Calculating the variance of the Moran I.
    
    :param x: Numpy array of the loads.
    :param w: Numpy array of the weight matrix.
    :param N: Integer number of samples (locations).

    :return var: Float of variance of Moran I.
    """

    W = w.sum()

    z = x - x.mean()

    s_1 = .5 * sum((w[i,j] + w[j,i])**2 for i in xrange(N) for j in xrange(N))

    s_2 = sum((sum(w[i,j] for j in xrange(N)) + sum(w[j,i] for j in xrange(N)))**2 for i in xrange(N))

    s_3 = (N**(-1) * (z**4).sum())/(N**(-1) * (z**2).sum())**2

    s_4 = (N**2 - 3.*N + 3.)*s_1 - N*s_2 + 3.*W**2

    s_5 = (N**2 - N)*s_1 - 2.*N*s_2 + 6.*W**2

    var = ((N*s_4 - s_3*s_5)/((N - 1.) * (N - 2.) * (N - 3.) * W**2)) - moran_expectation(N)**2

    return var


def z_score(I, expectation, variance):
    """Calculate the z-score for the Moran I.
    
    :param I: Float of Moran I.
    :param expectation: Float of expectation of Moran I.
    :param variance: Float of variance of Moran I.

    :return z: Float of z-score for the Moran I.
    """

    z = (I - expectation)/np.sqrt(variance)

    return z


def p_value(z):
    """Calculating the one and two sided p-value for the Moran z-score.
    
    :param z: Float of z-score for the Moran I.

    :return p_one_sided, p_two_sided: Float of one sided and two sided p values.
    """

    p_one_sided = st.norm.sf(abs(z)) 
    p_two_sided = st.norm.sf(abs(z))*2 

    return p_one_sided, p_two_sided