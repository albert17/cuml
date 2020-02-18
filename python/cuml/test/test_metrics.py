# Copyright (c) 2019, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import cuml
import numpy as np
import pytest

from cuml.ensemble import RandomForestClassifier as curfc
from cuml.metrics.cluster import adjusted_rand_score as cu_ars
from cuml.metrics import accuracy_score as cu_acc_score
from cuml.test.utils import get_handle, get_pattern, array_equal, \
    unit_param, quality_param, stress_param

from numba import cuda

from sklearn.datasets import make_classification
from sklearn.metrics import accuracy_score as sk_acc_score
from sklearn.metrics.cluster import adjusted_rand_score as sk_ars
from sklearn.metrics.cluster import homogeneity_score as sk_hom_score
from sklearn.metrics.cluster import mutual_info_score as sk_mi_score
from sklearn.metrics.cluster import completeness_score as sk_com_score
from sklearn.preprocessing import StandardScaler


@pytest.mark.parametrize('datatype', [np.float32, np.float64])
@pytest.mark.parametrize('use_handle', [True, False])
def test_r2_score(datatype, use_handle):
    a = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=datatype)
    b = np.array([0.12, 0.22, 0.32, 0.42, 0.52], dtype=datatype)

    a_dev = cuda.to_device(a)
    b_dev = cuda.to_device(b)

    handle, stream = get_handle(use_handle)

    score = cuml.metrics.r2_score(a_dev, b_dev, handle=handle)

    np.testing.assert_almost_equal(score, 0.98, decimal=7)


def test_sklearn_search():
    """Test ensures scoring function works with sklearn machinery
    """
    import numpy as np
    from cuml import Ridge as cumlRidge
    import cudf
    from sklearn import datasets
    from sklearn.model_selection import train_test_split, GridSearchCV
    diabetes = datasets.load_diabetes()
    X_train, X_test, y_train, y_test = train_test_split(diabetes.data,
                                                        diabetes.target,
                                                        test_size=0.2,
                                                        shuffle=False,
                                                        random_state=1)

    alpha = np.array([1.0])
    fit_intercept = True
    normalize = False

    params = {'alpha': np.logspace(-3, -1, 10)}
    cu_clf = cumlRidge(alpha=alpha, fit_intercept=fit_intercept,
                       normalize=normalize, solver="eig")

    assert getattr(cu_clf, 'score', False)
    sk_cu_grid = GridSearchCV(cu_clf, params, cv=5, iid=False)

    gdf_data = cudf.DataFrame.from_gpu_matrix(cuda.to_device(X_train))
    gdf_train = cudf.DataFrame(dict(train=y_train))

    sk_cu_grid.fit(gdf_data, gdf_train.train)
    assert sk_cu_grid.best_params_ == {'alpha': 0.1}


@pytest.mark.parametrize('nrows', [unit_param(30), quality_param(5000),
                         stress_param(500000)])
@pytest.mark.parametrize('ncols', [unit_param(10), quality_param(100),
                         stress_param(200)])
@pytest.mark.parametrize('n_info', [unit_param(7), quality_param(50),
                         stress_param(100)])
@pytest.mark.parametrize('datatype', [np.float32])
def test_accuracy(nrows, ncols, n_info, datatype):

    use_handle = True
    train_rows = np.int32(nrows*0.8)
    X, y = make_classification(n_samples=nrows, n_features=ncols,
                               n_clusters_per_class=1, n_informative=n_info,
                               random_state=123, n_classes=5)

    X_test = np.asarray(X[train_rows:, 0:]).astype(datatype)
    y_test = np.asarray(y[train_rows:, ]).astype(np.int32)
    X_train = np.asarray(X[0:train_rows, :]).astype(datatype)
    y_train = np.asarray(y[0:train_rows, ]).astype(np.int32)
    # Create a handle for the cuml model
    handle, stream = get_handle(use_handle, n_streams=8)

    # Initialize, fit and predict using cuML's
    # random forest classification model
    cuml_model = curfc(max_features=1.0,
                       n_bins=8, split_algo=0, split_criterion=0,
                       min_rows_per_node=2,
                       n_estimators=40, handle=handle, max_leaves=-1,
                       max_depth=16)

    cuml_model.fit(X_train, y_train)
    cu_predict = cuml_model.predict(X_test)
    cu_acc = cu_acc_score(y_test, cu_predict)
    cu_acc_using_sk = sk_acc_score(y_test, cu_predict)
    # compare the accuracy of the two models
    assert array_equal(cu_acc, cu_acc_using_sk)


dataset_names = ['noisy_circles', 'noisy_moons', 'aniso'] + \
                [pytest.param(ds, marks=pytest.mark.xfail)
                 for ds in ['blobs', 'varied']]


@pytest.mark.parametrize('name', dataset_names)
@pytest.mark.parametrize('nrows', [unit_param(20), quality_param(5000),
                         stress_param(500000)])
def test_rand_index_score(name, nrows):

    default_base = {'quantile': .3,
                    'eps': .3,
                    'damping': .9,
                    'preference': -200,
                    'n_neighbors': 10,
                    'n_clusters': 3}

    pat = get_pattern(name, nrows)

    params = default_base.copy()
    params.update(pat[1])

    cuml_kmeans = cuml.KMeans(n_clusters=params['n_clusters'])

    X, y = pat[0]

    X = StandardScaler().fit_transform(X)

    cu_y_pred = cuml_kmeans.fit_predict(X).to_array()

    cu_score = cu_ars(y, cu_y_pred)
    cu_score_using_sk = sk_ars(y, cu_y_pred)

    assert array_equal(cu_score, cu_score_using_sk)


@pytest.mark.parametrize('use_handle', [True, False])
def test_homogeneity_score(use_handle):
    def score_labeling(ground_truth, predictions):
        a = np.array(ground_truth, dtype=np.int32)
        b = np.array(predictions, dtype=np.int32)

        a_dev = cuda.to_device(a)
        b_dev = cuda.to_device(b)

        handle, stream = get_handle(use_handle)

        return cuml.metrics.homogeneity_score(a_dev, b_dev, handle=handle)

    # Perfect labelings are homogeneous
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [1, 1, 0, 0]),
                                   1.0, decimal=4)
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 0, 1, 1]),
                                   1.0, decimal=4)

    # Non-perfect labelings that further split classes into more clusters can
    # be perfectly homogeneous
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 0, 1, 2]),
                                   1.0, decimal=4)
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 1, 2, 3]),
                                   1.0, decimal=4)

    # Clusters that include samples from different classes do not make for an
    # homogeneous labeling
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 1, 0, 1]),
                                   0.0, decimal=4)
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 0, 0, 0]),
                                   0.0, decimal=4)


def generate_random_labels(random_generation_lambda, seed=1234):
    rng = np.random.RandomState(seed)  # makes it reproducible
    a = random_generation_lambda(rng)
    b = random_generation_lambda(rng)

    return cuda.to_device(a), cuda.to_device(b)


@pytest.mark.parametrize('use_handle', [True, False])
def test_homogeneity_score_big_array(use_handle):
    def assert_equal_sklearn(random_generation_lambda):
        a_dev, b_dev = generate_random_labels(random_generation_lambda)

        handle, stream = get_handle(use_handle)

        score = cuml.metrics.homogeneity_score(a_dev, b_dev, handle=handle)
        ref = sk_hom_score(a_dev, b_dev)

        np.testing.assert_almost_equal(score, ref, decimal=4)

    assert_equal_sklearn(lambda rng: rng.randint(0, 1000, int(10e4),
                                                 dtype=np.int32))
    assert_equal_sklearn(lambda rng: rng.randint(-1000, 1000, int(10e4),
                                                 dtype=np.int32))


def assert_mi_equal_sklearn(a, b, use_handle):
    a_dev = cuda.to_device(a)
    b_dev = cuda.to_device(b)

    handle, stream = get_handle(use_handle)

    score = cuml.metrics.mutual_info_score(a_dev, b_dev, handle=handle)
    ref = sk_mi_score(a_dev, b_dev)
    np.testing.assert_almost_equal(score, ref, decimal=4)


@pytest.mark.parametrize('use_handle', [True, False])
def test_mutual_info_score(use_handle):
    def assert_ours_equal_sklearn(ground_truth, predictions):
        a = np.array(ground_truth, dtype=np.int32)
        b = np.array(predictions, dtype=np.int32)
        assert_mi_equal_sklearn(a, b, use_handle=use_handle)

    assert_ours_equal_sklearn([0, 0, 1, 1], [1, 1, 0, 0])
    assert_ours_equal_sklearn([0, 0, 1, 1], [0, 0, 1, 1])
    assert_ours_equal_sklearn([0, 0, 1, 1], [0, 0, 1, 2])
    assert_ours_equal_sklearn([0, 0, 1, 1], [0, 1, 2, 3])
    assert_ours_equal_sklearn([0, 0, 1, 1], [0, 1, 0, 1])
    assert_ours_equal_sklearn([0, 0, 1, 1], [0, 0, 0, 0])


@pytest.mark.parametrize('use_handle', [True, False])
def test_mutual_info_score_big_array(use_handle):
    def assert_equal_sklearn(random_generation_lambda):
        rng = np.random.RandomState(1234)  # makes it reproducible
        a = random_generation_lambda(rng)
        b = random_generation_lambda(rng)
        assert_mi_equal_sklearn(a, b, use_handle=use_handle)

    assert_equal_sklearn(lambda rng: rng.randint(0, 1000, int(10e4),
                                                 dtype=np.int32))
    assert_equal_sklearn(lambda rng: rng.randint(-1000, 1000, int(10e4),
                                                 dtype=np.int32))


@pytest.mark.parametrize('use_handle', [True, False])
def test_homogeneity_completeness_symmetry(use_handle):
    def assert_hom_com_sym(random_generation_lambda, seed=1234):
        a_dev, b_dev = generate_random_labels(random_generation_lambda)
        handle, stream = get_handle(use_handle)
        hom = cuml.metrics.homogeneity_score(a_dev, b_dev, handle=handle)
        com = cuml.metrics.completeness_score(a_dev, b_dev, handle=handle)
        np.testing.assert_almost_equal(hom, com, decimal=7)

    assert_hom_com_sym(lambda rng: rng.randint(0, 2, int(10e3)))
    assert_hom_com_sym(lambda rng: rng.randint(-5, 20, int(10e3)))
    assert_hom_com_sym(lambda rng:
                       rng.randint(int(-10e5), int(10e5), int(10e3)))


@pytest.mark.parametrize('use_handle', [True, False])
def test_completeness_score(use_handle):
    def score_labeling(ground_truth, predictions):
        a = np.array(ground_truth, dtype=np.int)
        b = np.array(predictions, dtype=np.int)

        a_dev = cuda.to_device(a)
        b_dev = cuda.to_device(b)

        handle, stream = get_handle(use_handle)

        return cuml.metrics.completeness_score(a_dev, b_dev, handle=handle)

    # Perfect labelings are complete
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [1, 1, 0, 0]),
                                   1.0, decimal=4)
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 0, 1, 1]),
                                   1.0, decimal=4)

    # Non-perfect labelings that assign all classes members to the same
    # clusters are still complete
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 0, 0, 0]),
                                   1.0, decimal=4)
    np.testing.assert_almost_equal(score_labeling([0, 1, 2, 3], [0, 0, 1, 1]),
                                   1.0, decimal=4)

    # If classes members are split across different clusters, the assignment
    # cannot be complete
    np.testing.assert_almost_equal(score_labeling([0, 0, 1, 1], [0, 1, 0, 1]),
                                   0.0, decimal=4)
    np.testing.assert_almost_equal(score_labeling([0, 0, 0, 0], [0, 1, 2, 3]),
                                   0.0, decimal=4)


@pytest.mark.parametrize('use_handle', [True, False])
def test_completeness_score_big_array(use_handle):
    def assert_ours_equal_sklearn(random_generation_lambda):
        a_dev, b_dev = generate_random_labels(random_generation_lambda)

        handle, stream = get_handle(use_handle)

        score = cuml.metrics.completeness_score(a_dev, b_dev, handle=handle)
        ref = sk_com_score(a_dev, b_dev)

        np.testing.assert_almost_equal(score, ref, decimal=4)

    assert_ours_equal_sklearn(lambda rng: rng.randint(0, 1000, int(10e4)))
    assert_ours_equal_sklearn(lambda rng: rng.randint(-1000, 1000, int(10e4)))
