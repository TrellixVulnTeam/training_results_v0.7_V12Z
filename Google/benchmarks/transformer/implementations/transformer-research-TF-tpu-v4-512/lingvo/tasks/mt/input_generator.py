# Lint as: python2, python3
# Copyright 2018 The TensorFlow Authors. All Rights Reserved.
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
"""Machine translation input generator."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import REDACTED.transformer_lingvo.lingvo.compat as tf
from REDACTED.transformer_lingvo.lingvo.core import base_input_generator
from REDACTED.transformer_lingvo.lingvo.core import base_layer
from REDACTED.transformer_lingvo.lingvo.core import generic_input
from REDACTED.transformer_lingvo.lingvo.core import ops
from REDACTED.transformer_lingvo.lingvo.core import py_utils
from REDACTED.transformer_lingvo.lingvo.core import summary_utils
from REDACTED.transformer_lingvo.lingvo.core import tokenizers
from REDACTED.transformer_lingvo.lingvo.tasks.mt import text_input_pb2
import six

from REDACTED import descriptor_pb2


class NmtInput(base_input_generator.BaseSequenceInputGenerator):
  """Generator for NMT."""

  @classmethod
  def Params(cls):
    """Defaults params for `NmtInput`."""
    p = super(NmtInput, cls).Params()
    p.Define(
        'natural_order_model', True,
        'Whether the model consuming the input is a natural order model. Input '
        'is generated in natural order if True. Input is generated in reversed '
        'order if False. The value should be consistent with the underlying '
        'model. Set to True if training or using a natural order model, '
        'otherwise set to False.')
    p.tokenizer = tokenizers.VocabFileTokenizer.Params()
    p.source_max_length = 300
    return p

  def _DataSourceFromFilePattern(self, file_pattern):

    def Proc(record):
      """Parses a serialized tf.Example record."""
      outputs = [
          ('source_id', tf.io.VarLenFeature(tf.int64)),
          ('source_padding', tf.io.VarLenFeature(tf.float32)),
          ('target_id', tf.io.VarLenFeature(tf.int64)),
          ('target_padding', tf.io.VarLenFeature(tf.float32)),
          ('target_label', tf.io.VarLenFeature(tf.int64)),
          ('target_weight', tf.io.VarLenFeature(tf.float32)),
      ]
      features = tf.io.parse_single_example(record, dict(outputs))
      for k, v in six.iteritems(features):
        features[k] = v.values
      bucket_key = tf.cast(
          tf.maximum(
              tf.reduce_sum(1.0 - features['source_padding']),
              tf.reduce_sum(1.0 - features['target_padding'])), tf.int32)
      return [features[k] for k, _ in outputs], bucket_key

    return generic_input.GenericInput(
        file_pattern=file_pattern,
        processor=Proc,
        dynamic_padding_dimensions=[0] * 6,
        dynamic_padding_constants=[0, 1, 0, 1, 0, 0],
        **self.CommonInputOpArgs())

  @base_layer.initializer
  def __init__(self, params):
    super(NmtInput, self).__init__(params)
    p = self.params

    self.natural_order_model = p.natural_order_model

    (self._src_ids, self._src_paddings, self._tgt_ids, self._tgt_paddings,
     self._tgt_labels,
     self._tgt_weights), self._bucket_keys = self._BuildDataSource()

    if p.pad_to_max_seq_length:
      assert p.source_max_length

      if min(self.infeed_bucket_batch_limit) == max(
          self.infeed_bucket_batch_limit):
        source_shape = [
            min(self.infeed_bucket_batch_limit), p.source_max_length
        ]
        target_shape = [
            min(self.infeed_bucket_batch_limit), p.target_max_length
        ]
      else:
        source_shape = None
        target_shape = None
      self._src_ids = py_utils.PadSequenceDimension(self._src_ids,
                                                    p.source_max_length, 0,
                                                    source_shape)
      self._src_paddings = py_utils.PadSequenceDimension(
          self._src_paddings, p.source_max_length, 1, source_shape)
      self._tgt_ids = py_utils.PadSequenceDimension(self._tgt_ids,
                                                    p.target_max_length, 0,
                                                    target_shape)
      self._tgt_paddings = py_utils.PadSequenceDimension(
          self._tgt_paddings, p.target_max_length, 1, target_shape)
      self._tgt_labels = py_utils.PadSequenceDimension(self._tgt_labels,
                                                       p.target_max_length, 0,
                                                       target_shape)
      self._tgt_weights = py_utils.PadSequenceDimension(self._tgt_weights,
                                                        p.target_max_length, 0,
                                                        target_shape)

    # TODO(zhifengc): come up more meaningful training sample ids here.
    self._sample_ids = tf.range(0, self.InfeedBatchSize(), 1)

  def InfeedBatchSize(self):
    """Override BaseSequenceInputGenerator."""
    return tf.shape(self._src_ids)[0]

  def _InputBatch(self):
    ret = py_utils.NestedMap()

    ret.bucket_keys = self._bucket_keys

    ret.src = py_utils.NestedMap()
    ret.src.ids = tf.cast(self._src_ids, dtype=tf.int32)
    ret.src.paddings = self._src_paddings

    ret.tgt = py_utils.NestedMap()
    ret.tgt.ids = self._tgt_ids
    ret.tgt.labels = tf.cast(self._tgt_labels, dtype=tf.int32)
    ret.tgt.weights = self._tgt_weights
    ret.tgt.paddings = self._tgt_paddings

    if (self.params.fprop_dtype is None or
        self.params.dtype == self.params.fprop_dtype):
      return ret

    def _Cast(v):
      if not v.dtype.is_floating:
        return v
      return tf.cast(v, self.params.fprop_dtype)

    return ret.Transform(_Cast)


class MlPerfInput(base_input_generator.BaseSequenceInputGenerator):
  """Generator for MLPerf TFRecords."""

  @classmethod
  def Params(cls):
    """Default params for `MlPerfInput`."""
    p = super(MlPerfInput, cls).Params()

    p.Define('natural_order_model', True, '')
    p.Define(
        'sos_id', 0, 'Start of sentence id'
        'Note in the MLPerf encoding, this is actually <PAD>, however we can '
        'make use of it since we never actually use <PAD>.')

    p.Define(
        'packed_input', False,
        'If True, then we also consume {inputs,targets}_{position,segementation}'
    )
    p.Define('num_hosts', None, '')
    return p

  @base_layer.initializer
  def __init__(self, params):
    super(MlPerfInput, self).__init__(params)
    p = self.params
    self.natural_order_model = p.natural_order_model
    #self._sample_ids = tf.range(0, self.InfeedBatchSize(), 1)

  def PythonIdsToStrings(self, ids, lens):
    return self.tokenizer.PythonIdsToStrings(ids, lens)

  def InfeedBatchSize(self):
    """Override BaseSequenceInputGenerator."""
    return tf.shape(self._src_ids)[0]

  def _DataSourceFromFilePattern(self, file_pattern, task_id=None):
    tf.logging.info('blee_ds_from_pattern task_id=%s', task_id)
    p = self._params

    def _DerivePaddingsAndIds(src_ids, tgt_labels):
      """tgt_ids is tgt_labels shifted right by one, with a SOS ID prepended."""
      tgt_ids = tf.concat([[p.sos_id], tgt_labels[:-1]], axis=0)
      src_paddings = tf.zeros(tf.shape(src_ids), dtype=tf.float32)
      tgt_paddings = tf.zeros(tf.shape(tgt_ids), dtype=tf.float32)
      tgt_weights = tf.ones(tf.shape(tgt_ids), dtype=tf.float32)

      bucket_key = tf.cast(
          tf.maximum(
              tf.reduce_sum(1.0 - src_paddings),
              tf.reduce_sum(1.0 - tgt_paddings)), tf.int32)

      return src_paddings, tgt_ids, tgt_paddings, tgt_weights, bucket_key

    def _ProcPacked(record):
      """TFExample -> Tensors for PackedInput."""
      outputs = [
          ('inputs', tf.io.VarLenFeature(tf.int64)),
          ('targets', tf.io.VarLenFeature(tf.int64)),
          ('inputs_segmentation', tf.io.VarLenFeature(tf.int64)),
          ('inputs_position', tf.io.VarLenFeature(tf.int64)),
          ('targets_segmentation', tf.io.VarLenFeature(tf.int64)),
          ('targets_position', tf.io.VarLenFeature(tf.int64)),
          # Default eval weight to 1.0
          ('eval_weight',
           tf.io.FixedLenFeature([], tf.float32, default_value=1.0)),
      ]

      features = tf.io.parse_single_example(record, dict(outputs))
      for k, v in six.iteritems(features):
        if k != 'eval_weight':
          features[k] = v.values
        else:
          eval_weight = v

      src_ids = features['inputs']
      tgt_labels = features['targets']

      src_pos = features['inputs_position']
      src_seg = features['inputs_segmentation']

      tgt_pos = features['targets_position']
      tgt_seg = features['targets_segmentation']

      src_paddings, tgt_ids, tgt_paddings, tgt_weights, bucket_key = _DerivePaddingsAndIds(
          src_ids, tgt_labels)
      return [
          src_ids,
          src_paddings,
          tgt_ids,
          tgt_paddings,
          tgt_labels,
          tgt_weights,
          src_pos,
          src_seg,
          tgt_pos,
          tgt_seg,
          eval_weight,
      ], bucket_key

    def _Proc(record):
      """Parses a serialized tf.Example record."""
      outputs = [
          ('inputs', tf.io.VarLenFeature(tf.int64)),
          ('targets', tf.io.VarLenFeature(tf.int64)),
          # Default eval weight to 1.0
          ('eval_weight',
           tf.io.FixedLenFeature([], tf.float32, default_value=1.0)),
      ]
      features = tf.io.parse_single_example(record, dict(outputs))
      for k, v in six.iteritems(features):
        if k != 'eval_weight':
          features[k] = v.values
        else:
          eval_weight = v

      src_ids = features['inputs']
      tgt_labels = features['targets']

      # Derive trivial segmentation for unpacked input.
      src_paddings, tgt_ids, tgt_paddings, tgt_weights, bucket_key = _DerivePaddingsAndIds(
          src_ids, tgt_labels)

      src_len = tf.shape(src_ids)[0]
      tgt_len = tf.shape(tgt_ids)[0]
      src_pos = tf.range(src_len, dtype=tf.int32)
      src_seg = tf.zeros_like(src_paddings)
      tgt_pos = tf.range(tgt_len, dtype=tf.int32)
      tgt_seg = tf.zeros_like(tgt_paddings)

      return [
          src_ids, src_paddings, tgt_ids, tgt_paddings, tgt_labels, tgt_weights,
          src_pos, src_seg, tgt_pos, tgt_seg, eval_weight
      ], bucket_key

    if not p.packed_input:
      processor_fn = _Proc
    else:
      processor_fn = _ProcPacked

    if p.num_hosts and task_id is not None and p.use_per_host_infeed:
      partitioned_files = []
      # Strip off tfrecord: prefix.
      file_pattern = file_pattern[9:]
      files = tf.io.gfile.glob(file_pattern)
      assert len(files) > 0, 'Glob %s did not match any files.' % file_pattern
      # Get the correct partition for this host.
      for (i, f) in enumerate(files):
        if i % p.num_hosts == task_id:
          partitioned_files.append(f)
      assert len(partitioned_files
                ) > 0, 'Task %d has empty partitioned_files' % task_id
      file_pattern = 'tfrecord:' + ','.join(partitioned_files)
      tf.logging.info('filepattern: %s', file_pattern)
    return generic_input.GenericInput(
        file_pattern=file_pattern,
        processor=processor_fn,
        dynamic_padding_dimensions=[0] * 11,
        dynamic_padding_constants=[0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0],
        **self.CommonInputOpArgs())

  def _InputBatch(self, task_id=None):
    p = self.params
    (self._src_ids, self._src_paddings, self._tgt_ids, self._tgt_paddings,
     self._tgt_labels, self._tgt_weights, self._src_seg_pos, self._src_seg_ids,
     self._tgt_seg_pos, self._tgt_seg_ids,
     self._eval_weight), self._bucket_keys = self._BuildDataSource(
         task_id=task_id)

    if p.pad_to_max_seq_length:
      assert p.source_max_length

      if min(self.infeed_bucket_batch_limit) == max(
          self.infeed_bucket_batch_limit):
        source_shape = [
            min(self.infeed_bucket_batch_limit), p.source_max_length
        ]
        target_shape = [
            min(self.infeed_bucket_batch_limit), p.target_max_length
        ]
      else:
        source_shape = None
        target_shape = None
      self._src_ids = py_utils.PadSequenceDimension(self._src_ids,
                                                    p.source_max_length, 0,
                                                    source_shape)
      self._src_paddings = py_utils.PadSequenceDimension(
          self._src_paddings, p.source_max_length, 1, source_shape)
      self._tgt_ids = py_utils.PadSequenceDimension(self._tgt_ids,
                                                    p.target_max_length, 0,
                                                    target_shape)
      self._tgt_paddings = py_utils.PadSequenceDimension(
          self._tgt_paddings, p.target_max_length, 1, target_shape)
      self._tgt_labels = py_utils.PadSequenceDimension(self._tgt_labels,
                                                       p.target_max_length, 0,
                                                       target_shape)
      self._tgt_weights = py_utils.PadSequenceDimension(self._tgt_weights,
                                                        p.target_max_length, 0,
                                                        target_shape)

      self._src_seg_ids = py_utils.PadSequenceDimension(self._src_seg_ids,
                                                        p.source_max_length, 0,
                                                        source_shape)
      self._src_seg_pos = py_utils.PadSequenceDimension(self._src_seg_pos,
                                                        p.source_max_length, 0,
                                                        source_shape)
      self._tgt_seg_ids = py_utils.PadSequenceDimension(self._tgt_seg_ids,
                                                        p.target_max_length, 0,
                                                        target_shape)
      self._tgt_seg_pos = py_utils.PadSequenceDimension(self._tgt_seg_pos,
                                                        p.target_max_length, 0,
                                                        target_shape)
    self._eval_weight = tf.reshape(self._eval_weight, [self.InfeedBatchSize()])

    # BuildDataSource
    ret = py_utils.NestedMap()
    ret.bucket_keys = self._bucket_keys

    ret.src = py_utils.NestedMap()
    ret.src.ids = tf.cast(self._src_ids, dtype=tf.int32)
    ret.src.paddings = self._src_paddings

    ret.tgt = py_utils.NestedMap()
    ret.tgt.ids = self._tgt_ids
    ret.tgt.labels = tf.cast(self._tgt_labels, dtype=tf.int32)
    ret.tgt.weights = self._tgt_weights
    ret.tgt.paddings = self._tgt_paddings

    ret.src.segment_pos = self._src_seg_pos
    ret.src.segment_ids = self._src_seg_ids

    ret.tgt.segment_pos = self._tgt_seg_pos
    ret.tgt.segment_ids = self._tgt_seg_ids

    ret.eval_weight = self._eval_weight

    if (self.params.fprop_dtype is None or
        self.params.dtype == self.params.fprop_dtype):
      return ret

    def _Cast(v):
      if not v.dtype.is_floating:
        return v
      return tf.cast(v, self.params.fprop_dtype)

    return ret.Transform(_Cast)


def _GetSegmentPos(weights):
  """Returns a segment_pos tensor from the given weights tensor."""
  maxlen = tf.shape(weights)[1]
  ret = tf.cast(tf.range(maxlen), dtype=tf.float32)
  return tf.cast(weights * ret, dtype=tf.int32)


def _GetDescriptorSetForTextInput():
  """Returns a string for tf.io.decode_proto's descriptor_source."""
  file_descriptor_set = descriptor_pb2.FileDescriptorSet()
  text_input_pb2.DESCRIPTOR.CopyToProto(file_descriptor_set.file.add())
  return b'bytes://' + file_descriptor_set.SerializeToString()


class TextPackedInput(base_input_generator.BaseSequenceInputGenerator):
  """Generator for packed text input."""

  @classmethod
  def Params(cls):
    r"""Defaults params for TextInput.

    Returns:
      A Params object for TextPackedInput.

    Notes about usage:

    * Input files contain UTF8 encoded texts. p.input_file_type controls
      what format to extract these texts from. The default is 'tsv', in which
      case p.file_pattern should be prefixed by file type 'text:', and
      every line in the input file should have text columns separated by
      a tab '\t'. Otherwise p.input_file_type can be Sentence or SentencePair
      protos.

      For tsv input files, in the default case, the file should contain 2
      columns, for the source and the target sentence. Special cases:

      - When quality scores are present (see p.quality_score_filter_fn below),
        it should contain 3 columns, the last being a quality score.
      - When MASS is enabled, it should contain a single column.

    * p.tokenizer or p.tokenizer_dict is used to perform string to id
      conversions. If key `src` or `tgt` is present in p.tokenizer_dict,
      it will be used for generating the ids for src or tgt, respectively.
      Otherwise the default tokenizer will be used.

    * p.packing_factor depends on the training data and max lengths used.

      If this value is too small, we generate packed batches that contain
      too many padding that could have been used to pack more examples.
      If this value is too large, we use more memory and randomly discard
      examples that could not fit.

      One can look at the num_samples_in_batch graph to determine if its
      value is too small. For example, with an effective scaled batch size of
      1024, suppose we set p.packing_factor=3.0, and observe that
      num_samples_in_batch is saturated at 3072(=1024x3), this means 3.0 is
      likely too small. If we instead observe that num_samples_in_batch
      fluctuates around 2500, this means 3.0 is larger than needed.

      We believe that there can be a slight bias against longer sequences
      when packing is enabled. The remedy is either use larger effective
      batch size, or use a larger-than-optimal packing factor when effective
      batch size is smaller. For example, p.packing_factor = 8 seems to work
      reasonably well in practice.

    * p.source_max_length and p.target_max_length control both the shape of
      the generated input batch (how long each row is) and the filtering
      (max allowed lengths for source and targt, respectively).

      p.bucket_upper_bound also conrols the filtering of examples. Inputs
      with either source or target sequence lengths exceeding it will be
      filtered out.

      It's not meaningful to set p.bucket_upper_bound higher than both
      p.source_max_length and p.target_max_length.

      When packing is enabled, however, a smaller p.bucket_upper_bound means
      that individual sequences have a smaller max length, but the packed
      batch may have a larger total length.

    * p.file_pattern_task_ids, p.task_to_{src,tgt}_lang_map are all used
      to manipulate batch.{src,tgt}.task_ids.

      For each eaxmple, its task is obtained from the source id, which is
      the index of the example's origin file in p.file_pattern. The task
      id populated in the input batch is determined by:
      p.task_to_{src,tgt}_lang_map[ p.file_pattern_task_ids[souce_id] ],
      for src and tgt, respectively, where if a list is empty it falls
      back to an identity map.

      In the future we may define a separate lang_ids field to the input
      batch to disambiguate.

    * p.quality_score_filter_fn can be used when a column of quality score
      is present in the input .tsv file. The quality score must be the last
      column. This filter function returns True to filter, e.g. use
      p.quality_score_filter_fn = lambda x: x <= 0.3 for scores where higher
      means better.

      p.quality_score_filter_fn typically should only contain a simple
      comparison (<, >, <=, or >=), as it relies on tf.Tensor's overloading
      of __le__() etc. to work. For example: lambda x: ( 0.3 < x and x < 0.9)
      won't work. But tf.math.logical_and(0.3 < x, x < 0.9) is okay.

      Also note that 'p.quality_score_filter_fn = lambda _: False' is
      equivalent with 'p.quality_score_filter_fn = None', in which case
      no quality score column is needed (or evaluated).

    * Consider enabling multithreading for the trainer job (in the Train()
      method). For example: p.num_batcher_threads = 128.
    """
    p = super(TextPackedInput, cls).Params()

    p.Define('file_pattern_task_ids', [],
             'task_id corresponding to list of file_patterns.')
    p.Define('task_to_src_lang_map', [], 'Map of task id to src language id.')
    p.Define('task_to_tgt_lang_map', [], 'Map of task id to tgt language id.')

    p.Define(
        'packing_factor', None,
        'A multiplicative factor for packing. This is the ratio between '
        'pre-packing batch size and after-packing batch size. If None, '
        'packing is disabled; otherwise the packing factor should be a '
        'float with a value greater than 1.')

    p.Define(
        'quality_score_filter_fn', None,
        'A user defined boolean function on a float (quality score). '
        'When present, the input .tsv file has an additional column '
        'of floats representing a quality score, and each line is '
        'filtered out when this function returns True on that score.')

    p.Define(
        'input_file_type', 'tsv', 'The type of input file contents.'
        ' Must be one of ["tsv", "sentence_proto"], for tab-separated'
        ' values, or Sentence/SentencePair protos, respectively.')
    p.Define(
        'single_column_input', False, 'Indicates input is single-column rather'
        ' than double-column. When input_file_type is sentence_proto, this'
        ' means Sentence proto rather than SentencePair proto.')

    p.Define('natural_order_model', True, 'Only True is supported now.')
    p.Define('target_language', '', 'Language on target side.')
    p.Define('mass_layer', None, 'If not None, use the specified layer to do '
             'MASS masking.')
    return p

  @base_layer.initializer
  def __init__(self, params):
    super(TextPackedInput, self).__init__(params)
    p = self.params
    if not p.natural_order_model:
      raise ValueError('Only p.natural_order_model=True is supported now.')
    self.natural_order_model = p.natural_order_model

    if p.packing_factor:
      # Packing is enabled. We override p.bucket_batch_limit with the
      # pre-packing batch size.
      if p.packing_factor <= 1.0:
        raise ValueError('p.packing_factor must be > 1.0: ', p.packing_factor)
      if len(p.bucket_upper_bound) != 1 or len(p.bucket_batch_limit) != 1:
        raise ValueError(
            'when packing is enabled, p.bucket_upper_bound '
            'and p.bucket_batch_limits must be arrays of length '
            '1:', p.bucket_upper_bound, p.bucket_batch_limit)
      self._packed_batch_size = p.bucket_batch_limit[0]
      p.bucket_batch_limit[0] = int(p.bucket_batch_limit[0] * p.packing_factor)
    else:
      self._packed_batch_size = None

    # Ensure that the max lengths are not None, as tokenizer.StringsToIds()
    # might use it to pad the encoded ids tensor.
    if p.target_max_length is None:
      p.target_max_length = p.bucket_upper_bound[-1]
    if p.source_max_length is None:
      p.source_max_length = p.target_max_length

    if p.input_file_type not in ['tsv', 'sentence_proto']:
      raise ValueError('p.input_file_type must be one of ["tsv",'
                       ' "sentence_proto"], got {}'.format(
                           params.input_file_type))
    if p.quality_score_filter_fn:
      if not isinstance(p.quality_score_filter_fn(0.0), bool) and not (
          isinstance(p.quality_score_filter_fn(0.0), tf.Tensor) and
          p.quality_score_filter_fn(0.0).dtype == tf.bool):
        raise ValueError(
            'p.quality_score_filter_fn must return a bool on a float input, '
            'e.g. p.quality_score_filter_fn = lambda x: x <= 0.3.')
      if p.input_file_type != 'tsv':
        raise ValueError(
            'p.quality_score_filter_fn requires p.input_file_type == "tsv".')

    self._src_tokenizer_key = ('src' if 'src' in self.tokenizer_dict else
                               base_input_generator.DEFAULT_TOKENIZER_KEY)
    self._src_tokenizer = self.tokenizer_dict[self._src_tokenizer_key]
    self._tgt_tokenizer_key = ('tgt' if 'tgt' in self.tokenizer_dict else
                               base_input_generator.DEFAULT_TOKENIZER_KEY)
    self._tgt_tokenizer = self.tokenizer_dict[self._tgt_tokenizer_key]

    if p.single_column_input and p.mass_layer is None:
      raise NotImplementedError(
          'Single column input works only with MASS for now.')
    # TODO(alisonlui): Support single-column Sentence proto input.
    if p.single_column_input and p.input_file_type == 'sentence_proto':
      raise NotImplementedError(
          'Single column Sentence proto input not yet supported.')
    if p.mass_layer is not None and not p.single_column_input:
      raise ValueError('Must be single_column_input if mass layer is provided.')
    if p.mass_layer is not None:
      # Creat the MASS layer (wrapper for the MASS op).
      self.CreateChild('mass_layer', p.mass_layer)

    # A `.NestedMap` of input tensors for the current input batch.
    # We memoize it here to avoid accidentally calling self._BuildDataSource()
    # more than once.
    self._batch = self._DataSourceToInputBatch()

  def _GetBucketKey(self, features, filtered):
    """Returns a the bucket key for a given input."""
    # The token ids are not truncated if and only if it ends with padding
    # or the last id is EOS.
    src_fits = tf.math.logical_or(
        tf.math.equal(features.src.ids_indicator[-1], 0),
        tf.math.equal(features.src.ids[-1], self._src_tokenizer.eos_id))
    tgt_fits = tf.math.logical_or(
        tf.math.equal(features.tgt.ids_indicator[-1], 0),
        tf.math.equal(features.tgt.labels[-1], self._tgt_tokenizer.eos_id))

    # We return the max of sourcec or target sequence length if and only if both
    # src and tgt fit. Otherwise we return a key of -1 to filter out this input.
    def _MaxLen():
      src_len = tf.cast(
          tf.math.reduce_sum(features.src.ids_indicator), dtype=tf.int32)
      tgt_len = tf.cast(
          tf.math.reduce_sum(features.tgt.ids_indicator), dtype=tf.int32)
      return tf.math.maximum(src_len, tgt_len)

    filtered = tf.math.logical_or(
        filtered, tf.math.logical_not(tf.math.logical_and(src_fits, tgt_fits)))
    return tf.cond(filtered, lambda: -1, _MaxLen)

  def _GetTaskIds(self, source_id):
    """Look up the correct task_id from the source_id tensor."""
    if self.params.file_pattern_task_ids:
      file_task_ids = tf.constant(
          self.params.file_pattern_task_ids, dtype=tf.int32)
      source_id = tf.gather(file_task_ids, source_id)
    src_task_id = source_id
    tgt_task_id = source_id
    if self.params.task_to_src_lang_map:
      src_lang_ids = tf.constant(
          self.params.task_to_src_lang_map, dtype=tf.int32)
      src_task_id = tf.gather(src_lang_ids, src_task_id)
    if self.params.task_to_tgt_lang_map:
      tgt_lang_ids = tf.constant(
          self.params.task_to_tgt_lang_map, dtype=tf.int32)
      tgt_task_id = tf.gather(tgt_lang_ids, tgt_task_id)
    return src_task_id, tgt_task_id

  def _ProcessSingleInput(self, source_id, src, tgt):
    """Performs strings-to-ids on the given input pair via p.tokenizer_dict."""
    _, src_labels, src_paddings = self.StringsToIds(
        tf.reshape(src, [1]), is_source=True, key=self._src_tokenizer_key)
    tgt_ids, tgt_labels, tgt_paddings = self.StringsToIds(
        tf.reshape(tgt, [1]), is_source=False, key=self._tgt_tokenizer_key)
    # Mask positions to 0 where padding is 1 for consistency. We do this because
    # tokenizer implementation may use EOS token to pad.
    src_labels = py_utils.ApplyPadding(src_paddings, src_labels)
    tgt_ids = py_utils.ApplyPadding(tgt_paddings, tgt_ids)
    tgt_labels = py_utils.ApplyPadding(tgt_paddings, tgt_labels)

    features = py_utils.NestedMap()
    features.src = py_utils.NestedMap()
    features.src.ids = src_labels
    # ids_indicator is 1 if and only if the output from tokenizer has a
    # non-padded id. Unlike weights, it will not mutate and can be used for
    # determining actual sequence length, for example.
    features.src.ids_indicator = 1 - src_paddings
    features.tgt = py_utils.NestedMap()
    features.tgt.ids = tgt_ids
    features.tgt.labels = tgt_labels
    features.tgt.ids_indicator = 1 - tgt_paddings

    src_task_id, tgt_task_id = self._GetTaskIds(source_id)
    # task_ids are padded with zeros.
    features.src.task_ids = tf.cast(
        features.src.ids_indicator, dtype=tf.int32) * src_task_id
    features.tgt.task_ids = tf.cast(
        features.tgt.ids_indicator, dtype=tf.int32) * tgt_task_id

    if not py_utils.use_tpu():
      features.src.strs = src
      features.tgt.strs = tgt
    return features.Transform(tf.squeeze)

  def _ProcessMASSInput(self, source_id, src):
    """Perform MASS input processing."""
    # TODO(yuancao): By doing so we assume that right now for monolingual
    # eval/dev sets (xx->xx) are in double-column format (since it bypasses
    # the Mass op). Ideally we should add a dedicated eval/dev processing
    # procedure for unsupervised MT cases, so that single-column eval/devs sets
    # are also supported. This should not be handled by any specific ops like
    # Mass, but inside the TextPackedInput class.
    assert not self.do_eval, 'MASS input can only be used for training.'

    _, labels, paddings = self.StringsToIds(
        tf.reshape(src, [1]), is_source=True, key=self._src_tokenizer_key)
    weights = 1 - paddings
    actual_seq_len = tf.cast(tf.reduce_sum(weights, 1), tf.int32)
    src_lang_ids, tgt_lang_ids = self._GetTaskIds(source_id)

    mass_out = self.mass_layer.Mask(labels, weights, actual_seq_len)

    features = py_utils.NestedMap()
    features.src = py_utils.NestedMap()
    features.src.ids = mass_out.src.ids
    features.src.paddings = paddings
    features.src.weights = weights
    features.src.task_ids = tf.cast(
        features.src.weights, dtype=tf.int32) * src_lang_ids
    features.src.ids_indicator = weights
    features.tgt = py_utils.NestedMap()
    features.tgt.ids = mass_out.tgt.ids
    features.tgt.labels = mass_out.tgt.labels
    features.tgt.paddings = paddings
    features.tgt.weights = mass_out.tgt.weights
    features.tgt.task_ids = tf.ones_like(
        features.src.task_ids, dtype=tf.int32) * tgt_lang_ids
    features.tgt.ids_indicator = weights

    if not py_utils.use_tpu():
      features.src.strs = src
      features.tgt.strs = src
    return features.Transform(tf.squeeze)

  def _ReadRecordTsv(self, record):
    """Reads a single input record from a tab-separated values file."""
    # Assuming UTF8 text input separated by tabs.
    sentences = tf.strings.split([record], sep='\t', result_type='RaggedTensor')
    # If the row_lengths are not enough (e.g. row has only 1 column),
    # record_batcher throws away this record but it does not crash the program
    # per third_party/py/lingvo/core/ops/record_batcher.cc.
    # This means that it's okay if the file contains more columns than needed.
    src = sentences[0, 0]
    tgt = sentences[0, 1]
    # We manually filter the record if either source or target sentence is an
    # empty string.
    filtered = tf.math.logical_or(
        tf.math.equal(tf.strings.length(src), 0),
        tf.math.equal(tf.strings.length(tgt), 0))
    if not self.params.quality_score_filter_fn:
      return src, tgt, filtered
    filtered = tf.math.logical_or(
        filtered,
        self.params.quality_score_filter_fn(
            tf.strings.to_number(sentences[0, 2])))
    return src, tgt, filtered

  def _ReadRecordTsvSingleColumn(self, record):
    """Reads an input record, taking first column of one or more TSV columns."""
    # Assuming UTF8 text input which may have 1 or more tab-separated columns
    sentences = tf.strings.split([record], sep='\t', result_type='RaggedTensor')
    src = sentences[0, 0]
    filtered = tf.math.equal(tf.strings.length(src), 0)
    return src, filtered

  def _ReadRecordSentencePairProto(self, record):
    """Reads the input record as a binary SentencePair proto."""
    # We defer handling the `lang` field in the proto until TextPackedInput
    # figures out how to handle lang_ids. For now `lang` fields are ignored.
    _, sentence_protos = tf.io.decode_proto(
        bytes=record,
        message_type='tensorflow.babelfish.SentencePair',
        field_names=['src_sentence', 'tgt_sentence'],
        output_types=[tf.string, tf.string],
        descriptor_source=_GetDescriptorSetForTextInput())
    sentence_protos = tf.squeeze(sentence_protos)
    _, sentences = tf.io.decode_proto(
        bytes=sentence_protos,
        message_type='tensorflow.babelfish.Sentence',
        field_names=['sentence'],
        output_types=[tf.string],
        descriptor_source=_GetDescriptorSetForTextInput())
    sentences = tf.squeeze(sentences)
    return sentences[0], sentences[1]

  def _DataSourceFromFilePattern(self, file_pattern, input_source_weights=None):

    def Processor(source_id, record):
      """Parses a record, which is a line of text."""
      if self.params.input_file_type == 'tsv':
        if self.params.single_column_input:
          src, filtered = self._ReadRecordTsvSingleColumn(record)
          features = self._ProcessMASSInput(source_id, src)
        else:
          src, tgt, filtered = self._ReadRecordTsv(record)
          features = self._ProcessSingleInput(source_id, src, tgt)
      else:
        src, tgt = self._ReadRecordSentencePairProto(record)
        filtered = tf.constant(False, dtype=tf.bool)
        features = self._ProcessSingleInput(source_id, src, tgt)
      return features, self._GetBucketKey(features, filtered)

    return generic_input.GenericInput(
        processor=Processor,
        file_pattern=file_pattern,
        input_source_weights=input_source_weights,
        **self.CommonInputOpArgs())

  def _Pack(self, batch):
    """Packs a given batch.

    Note that this may change the batch size.

    This function packs the input batch and adds .segment_ids and .segment_pos
    fields to its `src` and `tgt` fields.

    Args:
      batch: a `.NestedMap` of input tensors to be packed. It is modified in
        place.
    """
    src_actual_seq_len = tf.math.reduce_sum(
        tf.cast(batch.src.ids_indicator, tf.int32), axis=1)
    tgt_actual_seq_len = tf.math.reduce_sum(
        tf.cast(batch.tgt.ids_indicator, tf.int32), axis=1)
    summary_utils.histogram('source_seq_lengths', src_actual_seq_len)
    summary_utils.histogram('target_seq_lengths', tgt_actual_seq_len)

    if not self.params.packing_factor:
      # Supply segment_ids and segment_pos with no packing.
      batch.src.segment_ids = batch.src.ids_indicator
      batch.src.segment_pos = _GetSegmentPos(batch.src.ids_indicator)
      batch.tgt.segment_ids = batch.tgt.ids_indicator
      batch.tgt.segment_pos = _GetSegmentPos(batch.tgt.ids_indicator)
      return

    (src_segment_ids, src_segment_pos, src_indices_in_input, tgt_segment_ids,
     tgt_segment_pos, tgt_indices_in_input) = ops.pack_sequences(
         src_actual_seq_len, tgt_actual_seq_len, self._ScaledBatchSize(),
         self.params.source_max_length, self.params.target_max_length)

    uniq_src_indices_in_input = tf.unique(
        tf.reshape(src_indices_in_input, [-1])).y
    uniq_tgt_indices_in_input = tf.unique(
        tf.reshape(tgt_indices_in_input, [-1])).y
    summary_utils.histogram(
        'packed_source_seq_lengths',
        tf.gather(src_actual_seq_len, uniq_src_indices_in_input, axis=0))
    summary_utils.histogram(
        'packed_target_seq_lengths',
        tf.gather(tgt_actual_seq_len, uniq_tgt_indices_in_input, axis=0))

    # We deferred adding .paddings and use its complement .ids_indicator
    # exclusively so that we can apply the packing with padding set to 0 for all
    # fields.
    def ApplyPackingToSource(x):
      if x.dtype == tf.string:
        return ops.apply_packing(x, '\t', src_segment_ids, src_indices_in_input)
      return ops.apply_packing(x, 0, src_segment_ids, src_indices_in_input)

    batch.src = batch.src.Transform(ApplyPackingToSource)
    batch.src.segment_ids = tf.cast(src_segment_ids, tf.float32)
    batch.src.segment_pos = src_segment_pos

    def ApplyPackingToTarget(x):
      if x.dtype == tf.string:
        return ops.apply_packing(x, '\t', tgt_segment_ids, tgt_indices_in_input)
      return ops.apply_packing(x, 0, tgt_segment_ids, tgt_indices_in_input)

    batch.tgt = batch.tgt.Transform(ApplyPackingToTarget)
    batch.tgt.segment_ids = tf.cast(tgt_segment_ids, tf.float32)
    batch.tgt.segment_pos = tgt_segment_pos

  def _ScaledBatchSize(self):
    # Adjust (post-packing) batch size according to the cluster spec.
    # See the impl of BaseSequenceInputGenerator.infeed_bucket_batch_limit()
    cluster = self.cluster
    batch_size = (self._packed_batch_size or self.params.bucket_batch_limit[0])
    scaled_batch_size = batch_size * cluster.num_splits_per_client
    if self.params.use_per_host_infeed and cluster.num_tpu_hosts > 0:
      scaled_batch_size = scaled_batch_size // cluster.num_tpu_hosts
    return scaled_batch_size

  def _DataSourceToInputBatch(self):
    """The current input batch as a `.NestedMap` of input tensors."""
    ret, _ = self._BuildDataSource()
    self._Pack(ret)
    if 'weights' not in ret.src or 'weights' not in ret.tgt:
      ret.src.weights = ret.src.ids_indicator
      ret.tgt.weights = ret.tgt.ids_indicator
    if 'paddings' not in ret.src or 'paddings' not in ret.tgt:
      ret.src.paddings = 1 - ret.src.weights
      ret.tgt.paddings = 1 - ret.tgt.weights
    del ret.src.ids_indicator
    del ret.tgt.ids_indicator

    if self.params.pad_to_max_seq_length:
      assert self.params.source_max_length

      def _EnsureSrcShape(x):
        if x.dtype == tf.string:
          return tf.ensure_shape(x, [self._ScaledBatchSize()])
        return tf.ensure_shape(
            x, [self._ScaledBatchSize(), self.params.source_max_length])

      def _EnsureTgtShape(x):
        if x.dtype == tf.string:
          return tf.ensure_shape(x, [self._ScaledBatchSize()])
        return tf.ensure_shape(
            x, [self._ScaledBatchSize(), self.params.target_max_length])

      ret.src = ret.src.Transform(_EnsureSrcShape)
      ret.tgt = ret.tgt.Transform(_EnsureTgtShape)

    summary_utils.histogram('source_token_ids', ret.src.ids)
    summary_utils.histogram('target_token_ids', ret.tgt.ids)

    # Casts floating point tensors to fprop_dtype before returning.
    return ret.Transform(self.Cast)

  def _InputBatch(self):
    """The current input batch.

    Returns:
      A `.NestedMap` of input tensors.
    """
    return self._batch

  def GlobalBatchSize(self):
    """Returns the total number of examples in the current batch."""
    # The number of examples is indicated by the segment_ids of the target.
    num_segments = tf.math.reduce_max(self._batch.tgt.segment_ids, axis=1)
    return tf.reduce_sum(tf.cast(num_segments, dtype=tf.int32))
