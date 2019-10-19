#!/usr/bin/env python3
""" S3FD Face detection plugin
https://arxiv.org/abs/1708.05237

Adapted from S3FD Port in FAN:
https://github.com/1adrianb/face-alignment
"""

from scipy.special import logsumexp
import numpy as np
import keras
import keras.backend as K

from lib.model.session import KSession
from ._base import Detector, logger


class Detect(Detector):
    """ S3FD detector for face recognition """
    def __init__(self, **kwargs):
        git_model_id = 11
        model_filename = "s3fd_keras_v1.h5"
        super().__init__(git_model_id=git_model_id, model_filename=model_filename, **kwargs)
        self.name = "S3FD"
        self.input_size = 640
        self.vram = 4112
        self.vram_warnings = 1024  # Will run at this with warnings
        self.vram_per_batch = 208
        self.batchsize = self.config["batch-size"]

    def init_model(self):
        """ Initialize S3FD Model"""
        confidence = self.config["confidence"] / 100
        model_kwargs = dict(custom_objects=dict(O2K_Add=O2K_Add,
                                                O2K_Slice=O2K_Slice,
                                                O2K_Sum=O2K_Sum,
                                                O2K_Sqrt=O2K_Sqrt,
                                                O2K_Pow=O2K_Pow,
                                                O2K_ConstantLayer=O2K_ConstantLayer,
                                                O2K_Div=O2K_Div))
        self.model = S3fd(self.model_path, model_kwargs, self.config["allow_growth"], confidence)

    def process_input(self, batch):
        """ Compile the detection image(s) for prediction """
        batch["feed"] = self.model.prepare_batch(batch["scaled_image"])
        return batch

    def predict(self, batch):
        """ Run model to get predictions """
        predictions = self.model.predict(batch["feed"])
        batch["prediction"] = self.model.finalize_predictions(predictions)
        logger.trace("filename: %s, prediction: %s", batch["filename"], batch["prediction"])
        return batch

    def process_output(self, batch):
        """ Compile found faces for output """
        return batch


################################################################################
# CUSTOM KERAS LAYERS
# generated by onnx2keras
################################################################################
class O2K_ElementwiseLayer(keras.engine.Layer):
    def __init__(self, **kwargs):
        super(O2K_ElementwiseLayer, self).__init__(**kwargs)

    def call(self, *args):
        raise NotImplementedError()

    def compute_output_shape(self, input_shape):
        # TODO: do this nicer
        ldims = len(input_shape[0])
        rdims = len(input_shape[1])
        if ldims > rdims:
            return input_shape[0]
        if rdims > ldims:
            return input_shape[1]
        lprod = np.prod(list(filter(bool, input_shape[0])))
        rprod = np.prod(list(filter(bool, input_shape[1])))
        return input_shape[0 if lprod > rprod else 1]


class O2K_Add(O2K_ElementwiseLayer):
    def call(self, x, *args):
        return x[0] + x[1]


class O2K_Slice(keras.engine.Layer):
    def __init__(self, starts, ends, axes=None, steps=None, **kwargs):
        self._starts = starts
        self._ends = ends
        self._axes = axes
        self._steps = steps
        super(O2K_Slice, self).__init__(**kwargs)

    def get_config(self):
        config = super(O2K_Slice, self).get_config()
        config.update({
            'starts': self._starts, 'ends': self._ends,
            'axes': self._axes, 'steps': self._steps
        })
        return config

    def get_slices(self, ndims):
        axes = self._axes
        steps = self._steps
        if axes is None:
            axes = tuple(range(ndims))
        if steps is None:
            steps = (1,) * len(axes)
        assert len(axes) == len(steps) == len(self._starts) == len(self._ends)
        return list(zip(axes, self._starts, self._ends, steps))

    def compute_output_shape(self, input_shape):
        input_shape = list(input_shape)
        for ax, start, end, steps in self.get_slices(len(input_shape)):
            size = input_shape[ax]
            if ax == 0:
                raise AttributeError("Can not slice batch axis.")
            if size is None:
                if start < 0 or end < 0:
                    raise AttributeError("Negative slices not supported on symbolic axes")
                logger.warning("Slicing symbolic axis might lead to problems.")
                input_shape[ax] = (end - start) // steps
                continue
            if start < 0:
                start = size - start
            if end < 0:
                end = size - end
            input_shape[ax] = (min(size, end) - start) // steps
        return tuple(input_shape)

    def call(self, x, *args):
        ax_map = dict((x[0], slice(*x[1:])) for x in self.get_slices(K.ndim(x)))
        shape = K.int_shape(x)
        slices = [(ax_map[a] if a in ax_map else slice(None)) for a in range(len(shape))]
        x = x[tuple(slices)]
        return x


class O2K_ReduceLayer(keras.engine.Layer):
    def __init__(self, axes=None, keepdims=True, **kwargs):
        self._axes = [axes] if isinstance(axes, int) else axes
        self._keepdims = bool(keepdims)
        super(O2K_ReduceLayer, self).__init__(**kwargs)

    def get_config(self):
        config = super(O2K_ReduceLayer, self).get_config()
        config.update({
            'axes': self._axes,
            'keepdims': self._keepdims
        })
        return config

    def compute_output_shape(self, input_shape):
        if self._axes is None:
            return (1,)*len(input_shape) if self._keepdims else tuple()
        ret = list(input_shape)
        for i in sorted(self._axes, reverse=True):
            if self._keepdims:
                ret[i] = 1
            else:
                ret.pop(i)
        return tuple(ret)

    def call(self, x, *args):
        raise NotImplementedError()


class O2K_Sum(O2K_ReduceLayer):
    def call(self, x, *args):
        return K.sum(x, self._axes, self._keepdims)


class O2K_Sqrt(keras.engine.Layer):
    def call(self, x, *args):
        return K.sqrt(x)


class O2K_Pow(keras.engine.Layer):
    def call(self, x, *args):
        return K.pow(*x)


class O2K_ConstantLayer(keras.engine.Layer):
    def __init__(self, constant_obj, dtype, **kwargs):
        self._dtype = np.dtype(dtype).name
        self._constant = np.array(constant_obj, dtype=self._dtype)
        super(O2K_ConstantLayer, self).__init__(**kwargs)

    def call(self, *args):
        # pylint:disable=arguments-differ
        data = K.constant(self._constant, dtype=self._dtype)
        return data

    def compute_output_shape(self, input_shape):
        return self._constant.shape

    def get_config(self):
        config = super(O2K_ConstantLayer, self).get_config()
        config.update({
            'constant_obj': self._constant,
            'dtype': self._dtype
        })
        return config


class O2K_Div(O2K_ElementwiseLayer):
    # pylint:disable=arguments-differ
    def call(self, x, *args):
        return x[0] / x[1]


class S3fd(KSession):
    """ Keras Network """
    def __init__(self, model_path, model_kwargs, allow_growth, confidence):
        logger.debug("Initializing: %s: (model_path: '%s', allow_growth: %s)",
                     self.__class__.__name__, model_path, allow_growth)
        super().__init__("S3FD", model_path, model_kwargs=model_kwargs, allow_growth=allow_growth)
        self.load_model()
        self.confidence = confidence
        logger.debug("Initialized: %s", self.__class__.__name__)

    @staticmethod
    def prepare_batch(batch):
        """ Prepare a batch for prediction """
        batch = batch - np.array([104.0, 117.0, 123.0])
        batch = batch.transpose(0, 3, 1, 2)
        return batch

    def finalize_predictions(self, bboxlists):
        """ Detect faces """
        ret = list()
        for i in range(bboxlists[0].shape[0]):
            bboxlist = [x[i:i+1, ...] for x in bboxlists]
            bboxlist = self.post_process(bboxlist)
            keep = self.nms(bboxlist, 0.3)
            bboxlist = bboxlist[keep, :]
            bboxlist = [x for x in bboxlist if x[-1] >= self.confidence]
            ret.append(np.array(bboxlist))
        return ret

    def post_process(self, bboxlist):
        """ Perform post processing on output
            TODO: do this on the batch.
        """
        retval = list()
        for i in range(len(bboxlist) // 2):
            bboxlist[i * 2] = self.softmax(bboxlist[i * 2], axis=1)
        for i in range(len(bboxlist) // 2):
            ocls, oreg = bboxlist[i * 2], bboxlist[i * 2 + 1]
            stride = 2 ** (i + 2)    # 4,8,16,32,64,128
            poss = zip(*np.where(ocls[:, 1, :, :] > 0.05))
            for _, hindex, windex in poss:
                axc, ayc = stride / 2 + windex * stride, stride / 2 + hindex * stride
                score = ocls[0, 1, hindex, windex]
                loc = np.ascontiguousarray(oreg[0, :, hindex, windex]).reshape((1, 4))
                priors = np.array([[axc / 1.0, ayc / 1.0, stride * 4 / 1.0, stride * 4 / 1.0]])
                variances = [0.1, 0.2]
                box = self.decode(loc, priors, variances)
                x_1, y_1, x_2, y_2 = box[0] * 1.0
                retval.append([x_1, y_1, x_2, y_2, score])
        retval = np.array(retval)
        if len(retval) == 0:
            retval = np.zeros((1, 5))
        return retval

    @staticmethod
    def softmax(inp, axis):
        """Compute softmax values for each sets of scores in x."""
        return np.exp(inp - logsumexp(inp, axis=axis, keepdims=True))

    @staticmethod
    def decode(loc, priors, variances):
        """Decode locations from predictions using priors to undo
        the encoding we did for offset regression at train time.
        Args:
            loc (tensor): location predictions for loc layers,
                Shape: [num_priors,4]
            priors (tensor): Prior boxes in center-offset form.
                Shape: [num_priors,4].
            variances: (list[float]) Variances of priorboxes
        Return:
            decoded bounding box predictions
        """
        boxes = np.concatenate((priors[:, :2] + loc[:, :2] * variances[0] * priors[:, 2:],
                                priors[:, 2:] * np.exp(loc[:, 2:] * variances[1])),
                               1)
        boxes[:, :2] -= boxes[:, 2:] / 2
        boxes[:, 2:] += boxes[:, :2]
        return boxes

    @staticmethod
    def nms(dets, thresh):
        # pylint:disable=too-many-locals
        """ Perform Non-Maximum Suppression """
        keep = list()
        if len(dets) == 0:
            return keep

        x_1, y_1, x_2, y_2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
        areas = (x_2 - x_1 + 1) * (y_2 - y_1 + 1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx_1, yy_1 = np.maximum(x_1[i], x_1[order[1:]]), np.maximum(y_1[i], y_1[order[1:]])
            xx_2, yy_2 = np.minimum(x_2[i], x_2[order[1:]]), np.minimum(y_2[i], y_2[order[1:]])

            width, height = np.maximum(0.0, xx_2 - xx_1 + 1), np.maximum(0.0, yy_2 - yy_1 + 1)
            ovr = width * height / (areas[i] + areas[order[1:]] - width * height)

            inds = np.where(ovr <= thresh)[0]
            order = order[inds + 1]

        return keep
