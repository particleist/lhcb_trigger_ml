import scipy.sparse as sparse
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.ensemble.gradient_boosting import LossFunction, LOSS_FUNCTIONS, MultinomialDeviance, MeanEstimator, \
    LogOddsEstimator, BinomialDeviance
import numpy
from sklearn.ensemble.weight_boosting import AdaBoostClassifier
from sklearn.tree.tree import DecisionTreeClassifier
from commonutils import generateSample


# class BinomialDeviance(LossFunction):
#     """Binomial deviance loss function for binary classification.
#
#     Binary classification is a special case; here, we only need to
#     fit one tree instead of ``n_classes`` trees.
#     """
#     def __init__(self, n_classes):
#         if n_classes != 2:
#             raise ValueError("{0:s} requires 2 classes.".format(
#                 self.__class__.__name__))
#         # we only need to fit one tree for binary clf.
#         super(BinomialDeviance, self).__init__(1)
#
#     def init_estimator(self):
#         return LogOddsEstimator()
#
#     def __call__(self, y, pred):
#         """Compute the deviance (= 2 * negative log-likelihood). """
#         # logaddexp(0, v) == log(1.0 + exp(v))
#         pred = pred.ravel()
#         return -2.0 * np.mean((y * pred) - np.logaddexp(0.0, pred))
#
#     def negative_gradient(self, y, pred, **kargs):
#         """Compute the residual (= negative gradient). """
#         return y - 1.0 / (1.0 + np.exp(-pred.ravel()))
#
#     def _update_terminal_region(self, tree, terminal_regions, leaf, X, y,
#                                 residual, pred):
#         """Make a single Newton-Raphson step.
#
#         our node estimate is given by:
#
#             sum(y - prob) / sum(prob * (1 - prob))
#
#         we take advantage that: y - prob = residual
#         """
#         terminal_region = np.where(terminal_regions == leaf)[0]
#         residual = residual.take(terminal_region, axis=0)
#         y = y.take(terminal_region, axis=0)
#
#         numerator = residual.sum()
#         denominator = np.sum((y - residual) * (1 - y + residual))
#
#         if denominator == 0.0:
#             tree.value[leaf, 0, 0] = 0.0
#         else:
#             tree.value[leaf, 0, 0] = numerator / denominator
import commonutils


class KnnLossFunction(LossFunction):
    def __init__(self, n_classes, coefficients_matrix, initial_weights=None):
        if n_classes != 2:
            raise NotImplementedError("Only 2 classes supported!")
        LossFunction.__init__(self, 1)
        self.coefficients_matrix = coefficients_matrix
        self.coefficients_matrix_t = coefficients_matrix.transpose()
        if initial_weights is None:
            initial_weights = numpy.ones(coefficients_matrix.shape[0])
        else:
            assert len(initial_weights) == coefficients_matrix.shape[0], "Different size"
        self.initial_weights = initial_weights

    def __call__(self, y, pred):
        """Computing the loss itself"""
        assert len(y) == len(pred) == self.coefficients_matrix.shape[1], "something is wrong with sizes"
        y_signed = 2 * y - 1
        exponents = numpy.exp(- self.coefficients_matrix.dot(y_signed * numpy.ravel(pred)))
        return (self.initial_weights * exponents).sum()

    def negative_gradient(self, y, pred, **kwargs):
        assert len(y) == len(pred) == self.coefficients_matrix.shape[1], "something is wrong with sizes"
        y_signed = 2 * y - 1
        exponents = numpy.exp(- self.coefficients_matrix.dot(y_signed * numpy.ravel(pred)))
        result = self.coefficients_matrix_t.dot(self.initial_weights * exponents) * y_signed
        return result

    def init_estimator(self):
        return LogOddsEstimator()

    def update_terminal_regions(self, tree, X, y, residual, y_pred,
                                sample_mask, learning_rate=1.0, k=0):
        y_signed = 2 * y - 1
        self.update_exponents = self.initial_weights * numpy.exp(- self.coefficients_matrix.dot(y_signed * numpy.ravel(y_pred)))
        LossFunction.update_terminal_regions(self, tree, X, y, residual, y_pred, sample_mask, learning_rate, k)

    def _update_terminal_region(self, tree, terminal_regions, leaf, X, y,
                                residual, pred):
        # terminal_region = numpy.where(terminal_regions == leaf)[0]
        y_signed = 2 * y - 1
        z = self.coefficients_matrix.dot((terminal_regions == leaf) * y_signed)
        alpha = sum(self.update_exponents * z) / (sum(self.update_exponents * z * z) + 1e-10)
        tree.value[leaf, 0, 0] = alpha


class PairwiseKnnLossFunction(KnnLossFunction):
    def __init__(self, trainX, trainY, uniform_variables, knn=5):
        is_signal = trainY > 0.5
        knn_signal = commonutils.computeSignalKnnIndices(uniform_variables, trainX, is_signal, knn)
        knn_bg = commonutils.computeSignalKnnIndices(uniform_variables, trainX, ~is_signal, knn)
        knn_bg[is_signal, :] = knn_signal[is_signal, :]
        coefficients_matrix = sparse.csr_matrix(len(trainX) * knn, len(trainX))
        for i in range(len(knn_bg)):
            for j in range(knn):
                row = i * knn + j
                coefficients_matrix[row, i] += 1
                coefficients_matrix[row, knn_bg[i, j]] += 1
        KnnLossFunction.__init__(self, 2, coefficients_matrix)


class SimpleKnnLossFunction(KnnLossFunction):
    def __init__(self, trainX, trainY, uniform_variables, knn=5):
        is_signal = trainY > 0.5
        knn_signal = commonutils.computeSignalKnnIndices(uniform_variables, trainX, is_signal, knn)
        knn_bg = commonutils.computeSignalKnnIndices(uniform_variables, trainX, ~is_signal, knn)
        knn_bg[is_signal, :] = knn_signal[is_signal, :]
        coefficients_matrix = sparse.csr_matrix(len(trainX), len(trainX))
        for i in range(len(knn_bg)):
            for j in range(knn):
                coefficients_matrix[i, knn_bg[i, j]] += 1
        KnnLossFunction.__init__(self, 2, coefficients_matrix)


class MyGradientBoostingClassifier(GradientBoostingClassifier):
    def _check_params(self):
        """Check validity of parameters and raise ValueError if not valid. """
        if self.n_estimators <= 0:
            raise ValueError("n_estimators must be greater than 0")

        if self.learning_rate <= 0.0:
            raise ValueError("learning_rate must be greater than 0")

        if isinstance(self.loss, LossFunction):
            self.loss_ = self.loss
        else:
            if self.loss not in LOSS_FUNCTIONS:
                raise ValueError("Loss '{0:s}' not supported. ".format(self.loss))

            if self.loss == 'deviance':
                loss_class = (MultinomialDeviance
                              if len(self.classes_) > 2
                              else BinomialDeviance)
            else:
                loss_class = LOSS_FUNCTIONS[self.loss]

            if self.loss in ('huber', 'quantile'):
                self.loss_ = loss_class(self.n_classes_, self.alpha)
            else:
                self.loss_ = loss_class(self.n_classes_)

        if self.subsample <= 0.0 or self.subsample > 1:
            raise ValueError("subsample must be in (0,1]")

        if self.init is not None:
            if (not hasattr(self.init, 'fit')
                    or not hasattr(self.init, 'predict')):
                raise ValueError("init must be valid estimator")
            self.init_ = self.init
        else:
            self.init_ = self.loss_.init_estimator()

        if not (0.0 < self.alpha and self.alpha < 1.0):
            raise ValueError("alpha must be in (0.0, 1.0)")



def testGradient(loss, size=1000):
    y = numpy.random.random(size) > 0.5
    pred = numpy.random.random(size)
    epsilon = 1e-6
    val = loss(y, pred)
    gradient = numpy.zeros_like(pred)

    for i in range(size):
        pred2 = pred.copy()
        pred2[i] += epsilon
        val2 = loss(y, pred2)
        gradient[i] = (val2 - val) / epsilon

    n_gradient = loss.negative_gradient(y, pred)
    assert numpy.all(abs(n_gradient + gradient) < 1e-4), "Problem with functional gradient"
    print "loss is ok"

testGradient(KnnLossFunction(2, 3 * sparse.eye(1000, 1000)))

def testGradientBoosting():
    # Generating some samples correlated with first variable
    dist = 0.6
    testX, testY = generateSample(2000, 10, dist)
    trainX, trainY = generateSample(2000, 10, dist)
    # We will try to get uniform distribution along this variable
    uniform_variables = ['column0']
    base_estimator = DecisionTreeClassifier(min_samples_split=20, max_depth=None)
    n_estimators = 40
    samples = 2000

    classifier = MyGradientBoostingClassifier(min_samples_split=20,
                                              loss=KnnLossFunction(2, sparse.eye(1000, samples)),
                                              max_depth=None, learning_rate=.2, n_estimators=n_estimators)
    classifier.fit(trainX[:samples], trainY[:samples])
    classifier.predict(testX)
    print classifier.score(testX, testY)
    print AdaBoostClassifier(n_estimators=n_estimators, base_estimator=base_estimator).fit(trainX, trainY)\
        .score(testX, testY)

    print 'uniform gradient boosting is ok'

testGradientBoosting()