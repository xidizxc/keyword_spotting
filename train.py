# encoding: utf-8

'''

@author: ZiqiLiu


@file: train.py

@time: 2017/5/18 上午11:03

@desc:
'''

# -*- coding:utf-8 -*-
# !/usr/bin/python

import sys
from config.config import get_config
from data_test import read_dataset

sys.dont_write_bytecode = True

import time
import datetime
import os

import numpy as np
import tensorflow as tf
from glob2 import glob
from models.dynamic_rnn import DRNN
from functools import reduce
from data_test import read_dataset
import time

model_path = './params/latest.ckpt'
# model_path = None
save_path = './params/'
DEBUG = False

os.environ["CUDA_VISIBLE_DEVICES"] = "0"


class Runner(object):
    def __init__(self):
        self.config = get_config()

    # @describe
    # def load_data(self, args, mode, type):
    #     if mode == 'train':
    #         return load_batched_data(train_mfcc_dir, train_label_dir, batch_size, mode, type)
    #     elif mode == 'test':
    #         return load_batched_data(test_mfcc_dir, test_label_dir, batch_size, mode, type)
    #     else:
    #         raise TypeError('mode should be train or test.')

    def run(self):
        # load data
        model = DRNN(self.config)
        global model_path
        model.config.show()
        self.data = read_dataset()

        print('fuck')
        with tf.Session(graph=model.graph) as sess:
            # restore from stored models
            if model_path is not None:
                model.saver.restore(sess, model_path)
                print(('Model restored from:' + model_path))
            else:
                files = glob(save_path + '*.ckpt.*')
                if len(files) > 0:
                    print(files)
                    raise Exception(
                        'existing param files. Please move them before initializing, otherwise will overwrite')
                print('Initializing')
                sess.run(model.initial_op)
            st_time = time.time()
            if self.config.is_training:
                try:
                    for step in range(10001):
                        x, y, seqLengths = self.data.next_batch(self.config.batch_size, False)
                        if not self.config.max_pooling_loss:
                            _, l = sess.run([model.optimizer, model.loss], feed_dict={model.inputX: x, model.inputY: y,
                                                                                      model.seqLengths: seqLengths})
                        else:
                            _, l, xent_bg, xent_max, max_log = sess.run(
                                [model.optimizer, model.loss, model.xent_background, model.xent_max_frame,
                                 model.max_index],
                                feed_dict={model.inputX: x, model.inputY: y,
                                           model.seqLengths: seqLengths})
                            print('step', step, xent_bg, xent_max)
                            # print(max_log)

                        if step % 200 == 0:
                            x, y, seqLengths, name = self.data.test_data()
                            _, logits, labels, seqLen = sess.run(
                                [model.optimizer, model.softmax, model.labels, model.seqLengths],
                                feed_dict={model.inputX: x, model.inputY: y,
                                           model.seqLengths: seqLengths})
                            # logits, labels = map((lambda a: a[:8]), (logits, labels))

                            for i, logit in enumerate(logits):
                                logits[seqLen[i]:] = 0

                            print(len(logits), len(labels), len(seqLen))

                            moving_average = [self.moving_average(record, self.config.smoothing_window, padding=True)
                                              for record in logits]

                            # print(moving_average[0].shape)
                            prediction = [
                                self.prediction(moving_avg, self.config.trigger_threshold, self.config.lockout)
                                for moving_avg in moving_average]
                            # print(prediction[0].shape)

                            result = [self.decode(p, self.config.word_interval) for p in prediction]
                            miss_rate, false_accept_rate = self.correctness(result)
                            print('--------------------------------')
                            print('step %d' % step)
                            print('loss:' + str(l))
                            print('miss rate:' + str(miss_rate))
                            print('flase_accept_rate:' + str(false_accept_rate))
                except KeyboardInterrupt:
                    if not DEBUG:
                        print('training shut down, the model will be save in %s' % save_path)
                        model.saver.save(sess, save_path=(save_path + 'latest.ckpt'))

                print('training finished, total step %d, the model will be save in %s' % (step, save_path))
                model.saver.save(sess, save_path=(save_path + 'latest.ckpt'))
            else:

                x, y, seqLengths, names = self.data.test_data()

                # x, y, seqLengths, names = self.data.test_data(self.config.validation_size,                                                              's_F193089BC92BAFDF_你好你是傻逼吗.wav')

                # print(len(seqLengths))

                _, logits, labels, seqLen = sess.run([model.optimizer, model.softmax, model.labels, model.seqLengths],
                                                     feed_dict={model.inputX: x, model.inputY: y,
                                                                model.seqLengths: seqLengths})
                # logits, labels = map((lambda a: a[:8]), (logits, labels))
                for i, logit in enumerate(logits):
                    logit[seqLen[i]:, :] = 0

                print(len(logits), len(labels), len(seqLen))

                moving_average = [self.moving_average(record, self.config.smoothing_window, padding=True)
                                  for record in logits]

                # print(len(moving_average))

                prediction = [
                    self.prediction(moving_avg, self.config.trigger_threshold, self.config.lockout, names[i])
                    for i, moving_avg in enumerate(moving_average)]
                # print(prediction[0].shape)


                ind = 6
                np.set_printoptions(precision=4, threshold=np.inf, suppress=True)
                print(str(names[ind]))

                with open('logits.txt', 'w') as f:
                    f.write(str(logits[ind]))
                with open('moving_avg.txt', 'w') as f:
                    f.write(str(moving_average[ind]))
                with open('trigger.txt', 'w') as f:
                    f.write(str(prediction[ind]))
                with open('label.txt', 'w') as f:
                    f.write(str([labels[ind]]))

                result = [self.decode(p, self.config.word_interval) for p in prediction]
                miss_rate, false_accept_rate = self.correctness(result)
                print('miss rate:' + str(miss_rate))
                print('flase_accept_rate:' + str(false_accept_rate))

    def prediction(self, moving_avg, threshold, lockout, f=None):
        if f is not None:
            print(f)
        # array is 2D array, moving avg for one record, whose shape is (t,p)
        # label is one-hot, which is also the same size of moving_avg
        # we assume label[0] is background
        # return a trigger array, the same size (t,p) (it's sth like mask)
        # print('=' * 50)
        num_class = moving_avg.shape[1]
        len_frame = moving_avg.shape[0]
        # print(num_class, len_frame)
        prediction = np.zeros(moving_avg.shape, dtype=np.float32)
        for i in range(1, num_class):
            j = 0
            while j < len_frame:
                if moving_avg[j][i] > threshold:
                    prediction[j][i] = 1
                j += 1
        return prediction

    def decode(self, prediction, word_interval):
        raw = [3, 2, 1]
        keyword = list(raw)
        # prediction based on moving_avg,shape(t,p),sth like one-hot, but can may overlapping
        # prediction = prediction[:, 1:]
        num_class = prediction.shape[1]
        len_frame = prediction.shape[0]
        pre = 0
        inter = 0

        target = keyword.pop()

        for frame in prediction:
            if frame.sum() > 0:
                if pre == 0:
                    assert frame.sum() == 1
                    index = np.nonzero(frame)[0]
                    pre = index[0]
                    if index == target:
                        if inter < word_interval:
                            if len(keyword) == 0:
                                return 1
                            target = keyword.pop()
                            continue

                    keyword = list(raw)
                    target = keyword.pop()
                    inter = 0
                    if index == target:
                        if len(keyword) == 0:
                            return 1
                        target = keyword.pop()
                        continue
                else:
                    if frame[pre] == 1:
                        continue
                    else:
                        index = np.nonzero(frame)[0]
                        pre = index
                        if index == target:
                            if len(keyword) == 0:
                                return 1
                            target = keyword.pop()
                        else:
                            keyword = list(raw)
                            target = keyword.pop()
                            if index == target:
                                if len(keyword) == 0:
                                    return 1
                                target = keyword.pop()
                                continue
            else:
                if pre == 0:
                    if len(raw) - len(keyword) > 1:
                        inter += 1
                else:
                    pre = 0

        return 0

    def correctness(self, result):
        target = [1, 1, 0, 0, 1, 0, 0, 0]
        assert len(result) == len(target)
        xor = target ^ result
        miss = xor & target
        false_accept = xor & target
        return miss / len(target), false_accept / len(target)

    def accuracy(self, prediction, label, latency):
        # for one record

        label[latency:, :] = label[latency:, :] + label[:-latency, :]
        label = np.clip(label, 0, 1)
        correct_trigger = prediction * label
        label_correct = 0
        # this only work for wav that keyword only appear once
        for i in range(1, label.shape[1]):
            if label[:, i].sum() > 0:
                label_correct += 1

        correct_trigger_num = correct_trigger.sum()

        false_accept = prediction.sum() - correct_trigger_num
        miss = label_correct - correct_trigger_num

        print('%d\t%d\t%d' % (label_correct, miss, false_accept))

        return np.asanyarray([miss, false_accept])

    def moving_average(self, array, n=5, padding=True):
        # array is 2D array, logits for one record, shape (t,p)
        # return shape (t,p)
        if n % 2 == 0:
            raise Exception('n must be odd')
        if len(array.shape) != 2:
            raise Exception('must be 2-D array.')
        if n > array.shape[0]:
            raise Exception('n larger than array length. the shape:' + str(array.shape))
        if padding:
            pad_num = n // 2
            array = np.pad(array=array, pad_width=((pad_num, pad_num), (0, 0)), mode='constant', constant_values=0)
        array = np.asarray([np.sum(array[i:i + n, :], axis=0) for i in range(len(array) - 2 * pad_num)]) / n
        return array


if __name__ == '__main__':
    runner = Runner()
    runner.run()
