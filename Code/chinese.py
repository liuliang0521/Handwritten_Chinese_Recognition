
#coding=utf-8
"""
Created on 2019/12/23

@author: shuang
"""
import tensorflow as tf
import os
import random
import tensorflow.contrib.slim as slim
import time
import logging
import numpy as np
import pickle
from PIL import Image

logger = logging.getLogger('Training a chinese write char recognition')
logger.setLevel(logging.INFO)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

# 最好不要用tf.app.flags 考虑使用absl.flags
# tf.app.flags.DEFINE_boolean('random_flip_up_down', False, "Whether to random flip up down")
# tf.app.flags.DEFINE_boolean('random_brightness', True, "whether to adjust brightness")
# tf.app.flags.DEFINE_boolean('random_contrast', True, "whether to random constrast")

# --charset_size change 3755 to 1000 --

tf.app.flags.DEFINE_integer('charset_size', 3755,
                            "Choose the first `charset_size` character to conduct our experiment.")
tf.app.flags.DEFINE_integer('image_size', 64, "Needs to provide same value as in training.")
tf.app.flags.DEFINE_boolean('gray', True, "whether to change the rbg to gray")
tf.app.flags.DEFINE_integer('max_steps', 20002, 'the max training steps ')
tf.app.flags.DEFINE_integer('eval_steps', 50, "the step num to eval")
tf.app.flags.DEFINE_integer('save_steps', 2000, "the steps to save")

tf.app.flags.DEFINE_string('checkpoint_dir', 'D:/TFRECORD/data/checkpoint/', 'the checkpoint dir')
tf.app.flags.DEFINE_string('train_data_dir', 'D:/TFRECORD/data/train/', 'the train dataset dir')
tf.app.flags.DEFINE_string('test_data_dir', 'D:/TFRECORD/data/test/', 'the test dataset dir')
tf.app.flags.DEFINE_string('logs_dir', 'D:/TFRECORD/data/log/', 'the logging dir')

tf.app.flags.DEFINE_boolean('restore', True, 'whether to restore from checkpoint')
tf.app.flags.DEFINE_boolean('epoch', 1, 'Number of epoches')
tf.app.flags.DEFINE_integer('batch_size', 128, 'Validation batch size')
tf.app.flags.DEFINE_string('mode', 'inference', 'Running mode. One of {"train", "valid", "test"}')
FLAGS = tf.app.flags.FLAGS


class DataIterator:
    def __init__(self, data_dir):
        # Set FLAGS.charset_size to a small value if available computation power is limited.
        truncate_path = data_dir + ('%05d' % FLAGS.charset_size)
        print(truncate_path)
        print(len(truncate_path))
        self.image_names = []
        for root, sub_folder, file_list in os.walk(data_dir):
            # print(root)
            if root < truncate_path:  # eg. root='train/00000' truncate_path='D:/TFRECORD/data/train/01000'
                self.image_names += [os.path.join(root, file_path) for file_path in file_list]
        random.shuffle(self.image_names)
        self.labels = [int(file_name[len(data_dir):].split(os.sep)[0]) for file_name in self.image_names]

    @property
    def size(self):
        return len(self.labels)

    @staticmethod
    def data_augmentation(images):
        if FLAGS.random_flip_up_down:
            images = tf.image.random_flip_up_down(images)
        if FLAGS.random_brightness:
            images = tf.image.random_brightness(images, max_delta=0.3)
        if FLAGS.random_contrast:
            images = tf.image.random_contrast(images, 0.8, 1.2)
        return images

    def input_pipeline(self, batch_size, num_epochs=None):
        # num_epochs: An integer (optional). If specified, slice_input_producer produces each slice num_epochs times
        # before generating an OutOfRange error. If not specified, slice_input_producer can cycle through the slices
        # an unlimited number of times.

        images_tensor = tf.convert_to_tensor(self.image_names, dtype=tf.string)
        labels_tensor = tf.convert_to_tensor(self.labels, dtype=tf.int64)
        input_queue = tf.train.slice_input_producer([images_tensor, labels_tensor], num_epochs=num_epochs)

        labels = input_queue[1]
        images_content = tf.read_file(input_queue[0])
        images = tf.image.convert_image_dtype(tf.image.decode_png(images_content, channels=1),
                                              tf.float32)  # tf.image.decode_png()channels=1 means output a grayscale
        #  image
        #        if aug:
        #            images = self.data_augmentation(images)
        new_size = tf.constant([FLAGS.image_size, FLAGS.image_size], dtype=tf.int32)
        images = tf.image.resize_images(images, new_size)
        image_batch, label_batch = tf.train.shuffle_batch([images, labels], batch_size=batch_size, capacity=50000,
                                                          min_after_dequeue=10000)
        # min_after_dequeue: Minimum number elements in the queue after a dequeue, used to ensure a level of mixing
        # of elements.
        return image_batch, label_batch


def build_graph(top_k):
    # with tf.device('/gpu:0'):
    keep_prob = tf.placeholder(dtype=tf.float32, shape=[], name='keep_prob')
    images = tf.placeholder(dtype=tf.float32, shape=[None, 64, 64, 1], name='image_batch')
    labels = tf.placeholder(dtype=tf.int64, shape=[None], name='label_batch')
    
    conv_1 = slim.conv2d(images, 64, [3, 3], 1, padding='SAME', scope='conv1')
    max_pool_1 = slim.max_pool2d(conv_1, [2, 2], [2, 2], padding='SAME')
    conv_2 = slim.conv2d(max_pool_1, 128, [3, 3], padding='SAME', scope='conv2')
    max_pool_2 = slim.max_pool2d(conv_2, [2, 2], [2, 2], padding='SAME')
    conv_3 = slim.conv2d(max_pool_2, 256, [3, 3], padding='SAME', scope='conv3')
    max_pool_3 = slim.max_pool2d(conv_3, [2, 2], [2, 2], padding='SAME')

    flatten = slim.flatten(max_pool_3)
    fc1 = slim.fully_connected(slim.dropout(flatten, keep_prob), 1024, activation_fn=tf.nn.tanh, scope='fc1')
    logits = slim.fully_connected(slim.dropout(fc1, keep_prob), FLAGS.charset_size, activation_fn=None,
                                      scope='fc2')  # Optional scope for variable_scope.
        # logits = slim.fully_connected(flatten, FLAGS.charset_size, activation_fn=None, reuse=reuse, scope='fc')
    # with tf.device('/cpu:0'):
    loss = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(logits=logits,
                                                                             labels=labels))  # Computes the mean of
        # elements across dimensions of a tensor
        # the difference with tf.nn.softmax_cross_entropy_with_logits : needs one_hot labels.
    # with tf.device('/gpu:0'):
    accuracy = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(logits, 1), labels), tf.float32))

    global_step = tf.get_variable("step", [], initializer=tf.constant_initializer(0.0), trainable=False)
    rate = tf.train.exponential_decay(2e-4, global_step, decay_steps=2000, decay_rate=0.97,
                                          staircase=True)  # Applies exponential decay to the learning rate.
    train_op = tf.train.AdamOptimizer(learning_rate=rate).minimize(loss, global_step=global_step)
	# with tf.device('/cpu:0'):
    probabilities = tf.nn.softmax(logits)

    predicted_val_top_k, predicted_index_top_k = tf.nn.top_k(probabilities, k=top_k)
    accuracy_in_top_k = tf.reduce_mean(tf.cast(tf.nn.in_top_k(probabilities, labels, top_k), tf.float32))
    tf.summary.scalar('loss', loss)  # Summaries provide a way to export condensed information about a model,
    tf.summary.scalar('accuracy', accuracy)  # which is then accessible in tools such as TensorBoard.
    tf.summary.scalar('top_k', accuracy_in_top_k)
    merged_summary_op = tf.summary.merge_all()

    return {'images': images,
            'labels': labels,
            'keep_prob': keep_prob,
            'top_k': top_k,
            'global_step': global_step,
            'train_op': train_op,
            'loss': loss,
            'accuracy': accuracy,
            'accuracy_top_k': accuracy_in_top_k,
            'merged_summary_op': merged_summary_op,
            'predicted_distribution': probabilities,
            'predicted_index_top_k': predicted_index_top_k,
            'predicted_val_top_k': predicted_val_top_k}


def train():
    print('Begin training')
    train_feeder = DataIterator(data_dir='D:/TFRECORD/data/train/')
    test_feeder = DataIterator(data_dir='D:/TFRECORD/data/test/')
    with tf.Session() as sess:
        train_images, train_labels = train_feeder.input_pipeline(batch_size=FLAGS.batch_size)
        test_images, test_labels = test_feeder.input_pipeline(batch_size=FLAGS.batch_size)
        graph = build_graph(top_k=1)
        sess.run(tf.global_variables_initializer())
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)
        saver = tf.train.Saver()

        train_writer = tf.summary.FileWriter(FLAGS.logs_dir + '/train', sess.graph)
        test_writer = tf.summary.FileWriter(FLAGS.logs_dir + '/val')
        start_step = 0
        if FLAGS.restore:
            ckpt = tf.train.latest_checkpoint(FLAGS.checkpoint_dir)
            if ckpt:
                saver.restore(sess, ckpt)
                print("restore from the checkpoint {0}".format(ckpt))
                start_step += int(ckpt.split('-')[-1])  # why ckpt.split('-') find the restored global step

        logger.info(':::Training Start:::')
        try:
            while not coord.should_stop():
                start_time = time.time()  # Return the time in seconds since the epoch as a floating point number.
                train_images_batch, train_labels_batch = sess.run([train_images, train_labels])
                feed_dict = {graph['images']: train_images_batch,
                             graph['labels']: train_labels_batch,
                             graph['keep_prob']: 0.8}  # use 'keep_prob' argument to
                _, loss_val, train_summary, step = sess.run(
                    [graph['train_op'], graph['loss'], graph['merged_summary_op'], graph['global_step']],
                    feed_dict=feed_dict)  # what's the returns of sess.run()
                train_writer.add_summary(train_summary, step)
                end_time = time.time()
                logger.info("the step {0} takes {1} loss {2}".format(step, end_time - start_time, loss_val))
                if step > FLAGS.max_steps:
                    break
                if step % FLAGS.eval_steps == 1:
                    test_images_batch, test_labels_batch = sess.run([test_images, test_labels])
                    feed_dict = {graph['images']: test_images_batch,
                                 graph['labels']: test_labels_batch,
                                 graph['keep_prob']: 1.0}
                    accuracy_test, test_summary = sess.run(
                        [graph['accuracy'], graph['merged_summary_op']],
                        feed_dict=feed_dict)
                    test_writer.add_summary(test_summary, step)
                    logger.info('===============Eval a batch=======================')
                    logger.info('the step {0} test accuracy: {1}'
                                .format(step, accuracy_test))
                    logger.info('===============Eval a batch=======================')
                if step % FLAGS.save_steps == 1:
                    logger.info('Save the ckpt of {0}'.format(step))
                    saver.save(sess, os.path.join(FLAGS.checkpoint_dir, 'my-model'),
                               global_step=graph['global_step'])
        except tf.errors.OutOfRangeError:  # Raised when an operation iterates past the valid input range.
            logger.info('==================Train Finished================')
            saver.save(sess, os.path.join(FLAGS.checkpoint_dir, 'my-model'), global_step=graph['global_step'])
            # global_step: If provided the global step number is appended to save_path to create the checkpoint
            # filenames. The optional argument can be a Tensor, a Tensor name or an integer.
        finally:
            coord.request_stop()
        coord.join(threads)


def validation():
    print('validation')
    test_feeder = DataIterator(data_dir='D:/TFRECORD/data/test/')

    final_predict_val = []
    final_predict_index = []
    groundtruth = []

    with tf.Session() as sess:
        test_images, test_labels = test_feeder.input_pipeline(batch_size=FLAGS.batch_size, num_epochs=1)
        graph = build_graph(3)

        sess.run(tf.global_variables_initializer())
        sess.run(tf.local_variables_initializer())  # initialize test_feeder's inside state

        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)

        saver = tf.train.Saver()
        ckpt = tf.train.latest_checkpoint(FLAGS.checkpoint_dir)
        if ckpt:
            saver.restore(sess, ckpt)
            print("restore from the checkpoint {0}".format(ckpt))

        logger.info(':::Start validation:::')
        try:
            i = 0
            acc_top_1, acc_top_k = 0.0, 0.0
            while not coord.should_stop():
                i += 1
                start_time = time.time()
                test_images_batch, test_labels_batch = sess.run([test_images, test_labels])
                feed_dict = {graph['images']: test_images_batch,
                             graph['labels']: test_labels_batch,
                             graph['keep_prob']: 1.0}
                batch_labels, probs, indices, acc_1, acc_k = sess.run([graph['labels'],
                                                                       graph['predicted_val_top_k'],
                                                                       graph['predicted_index_top_k'],
                                                                       graph['accuracy'],
                                                                       graph['accuracy_top_k']], feed_dict=feed_dict)
                final_predict_val += probs.tolist()
                final_predict_index += indices.tolist()  # Return the array as a (possibly nested) list.
                groundtruth += batch_labels.tolist()
                acc_top_1 += acc_1
                acc_top_k += acc_k
                end_time = time.time()
                logger.info("the batch {0} takes {1} seconds, accuracy = {2}(top_1) {3}(top_k)"
                            .format(i, end_time - start_time, acc_1, acc_k))

        except tf.errors.OutOfRangeError:
            logger.info('==================Validation Finished================')
            acc_top_1 = acc_top_1 * FLAGS.batch_size / test_feeder.size  # calculate the mean average
            acc_top_k = acc_top_k * FLAGS.batch_size / test_feeder.size
            logger.info('top 1 accuracy {0} top k accuracy {1}'.format(acc_top_1, acc_top_k))
        finally:
            coord.request_stop()
        coord.join(threads)
    return {'prob': final_predict_val, 'indices': final_predict_index, 'groundtruth': groundtruth}

class StrToBytes:  
    def __init__(self, fileobj):  
        self.fileobj = fileobj  
    def read(self, size):  
        return self.fileobj.read(size).encode()  
    def readline(self, size=-1):  
        return self.fileobj.readline(size).encode()

# 获取汉字label映射表
def get_label_dict():
    # f=open('./chinese_labels','r')
    # label_dict = pickle.load(f)
    # f.close()
    with open('E:/TFRECORD/data/chinese_labels', 'r') as data_file:
        label_dict = pickle.load(StrToBytes(data_file))
        return label_dict

# 获待预测图像文件夹内的图像名字
def get_file_list(path):
    list_name=[]
    files = os.listdir(path)
    files.sort()
    for file in files:
        file_path = os.path.join(path, file)
        list_name.append(file_path)
    return list_name

def inference(name_list):
    print('inference')
    image_set=[]
    # 对每张图进行尺寸标准化和归一化
    for image in name_list:
        temp_image = Image.open(image).convert('L')
        temp_image = temp_image.resize((FLAGS.image_size, FLAGS.image_size), Image.ANTIALIAS)
        temp_image = np.asarray(temp_image) / 255.0
        temp_image = temp_image.reshape([-1, 64, 64, 1])
        image_set.append(temp_image)
        
    # allow_soft_placement 如果你指定的设备不存在，允许TF自动分配设备
    with tf.Session() as sess:
        logger.info('========start inference============')
        # images = tf.placeholder(dtype=tf.float32, shape=[None, 64, 64, 1])
        # Pass a shadow label 0. This label will not affect the computation graph.
        graph = build_graph(top_k=3)
        saver = tf.train.Saver()
        # 自动获取最后一次保存的模型
        ckpt = tf.train.latest_checkpoint(FLAGS.checkpoint_dir)
        if ckpt:       
            saver.restore(sess, ckpt)
        val_list=[]
        idx_list=[]
        # 预测每一张图
        for item in image_set:
            temp_image = item
            predict_val, predict_index = sess.run([graph['predicted_val_top_k'], graph['predicted_index_top_k']],
                                              feed_dict={graph['images']: temp_image,
                                                         graph['keep_prob']: 1.0})
            val_list.append(predict_val)
            idx_list.append(predict_index)
    #return predict_val, predict_index
    return val_list,idx_list


def main(_):
    print(FLAGS.mode)
    if FLAGS.mode == "train":
        train()
    elif FLAGS.mode == 'validation':
        dct = validation()
        result_file = 'result.dict'
        logger.info('Write result into {0}'.format(result_file))
        with open(result_file, 'wb') as f:
            pickle.dump(dct, f)
        logger.info('Write file ends')
    elif FLAGS.mode == 'inference':
        label_dict = get_label_dict()
        name_list = get_file_list('D:/data/tmp/')
        final_predict_val, final_predict_index = inference(name_list)
        # image_path = './tmp/128.jpg'
        # final_predict_val, final_predict_index = inference(image_path)
        # logger.info('the result info label {0} predict index {1} predict_val {2}'.format(final_predict_index[0][0], final_predict_index,final_predict_val))
        # logger.info('|{0},{1:.0%}|{2},{3:.0%}|{4},{5:.0%}|'.format(label_dict[int(final_predict_index[0][0])],final_predict_val[0][0],label_dict[int(final_predict_index[0][1])],final_predict_val[0][1],label_dict[int(final_predict_index[0][2])],final_predict_val[0][2]))
        final_reco_text =[]  # 存储最后识别出来的文字串
        # 给出top 3预测，candidate1是概率最高的预测
        count=0
        for i in range(len(final_predict_val)):
            candidate1 = final_predict_index[i][0][0]
            candidate2 = final_predict_index[i][0][1]
            candidate3 = final_predict_index[i][0][2]
            final_reco_text.append(label_dict[int(candidate1)])
            str=name_list[i]
            num=''.join([x for x in str if x.isdigit()])
            
            #print(int(num),)
            
            logger.info('[the result info] image: {0} predict: {1} {2} {3}; predict index {4} predict_val {5}'.format(str[14:], 
                label_dict[int(candidate1)],label_dict[int(candidate2)],label_dict[int(candidate3)],final_predict_index[i],final_predict_val[i]))
            print(label_dict[int(candidate1)])
            print(num,)
            str1='帅哥龚龙龋龄齿齐鼻鼠豉鼎默黔黑黎黍黄麻考麓鹿鹰鹤鹏鹊鹅鹃鸿鸽驼鸳鸯鸭鸦鸥鸣鸡鸟麟鳖鳃鲸鲤鲜鲍鲁鱼魔魏魄魂魁鬼鬃高髓骸骨骤骡骚骗骑骏验骋骇骆骄骂驾驼驻驹驶驴驳驱驰驯驮驭马香首馒馏馋馈馆馅馁饿饼饺饶饵饲饱饰饯饮饭饥餐食飞飘风颧颤颠额颜题颗颖颓频颐颊领颇领颅预颂颁顿顾顽须顺项顷顶页韶韵音韭韩韧韦鞭鞠鞘鞍鞋靶靴靳革面靡靠非靛静请青霹霸露霞霜霖霓霍霉震霄需雾雹雷零雪雨雕雏雍雌雇集雅雄雁雀难隶隧障隙隘隔隐随隋隆隅陷陶陵陪险陨除院陡陛陜限降陌陋阵陇陆际附陀阿阻阶阵阴阳防阮队阜阔阑阐阎阉阅阂阁阀闽闻闺闹闸闷间闲闰闯问闭闪门长镶镰镭镣镜镑稿镍镊镇镁镀锻锹锰锯键锭锨锦锥锤锣锡锚错锗锑锐锌锋锈锅锄琐销链铺铸银铲铱铰铭铬铣铡铝铜铆铅铃铂铁铀钾钻钵钳钱钮钩钨钧钦钥钢钡钠钟钊钝钙钓钒钎钉针鉴釜金量野重里释釉采醛醚醒醋醉醇酿酸酷酶酵酱酮酬酪酥酣酞酝酚酗酒配酌酋酉鄙鄂都郸郴郭部郧郡郝郑郎郊郁邻邹邵邱邯邮邪邦那邢邓邑邀避遵遮'
            if str1[int(num)]==label_dict[int(candidate1)] or str1[int(num)]==label_dict[int(candidate2)] or str1[int(num)]==label_dict[int(candidate3)]:count=count+1
        print(count)
        #print ('=====================OCR RESULT=======================\n')
        # 打印出所有识别出来的结果（取top 1）
        #for i in range(len(final_reco_text)):
           #print(final_reco_text[i],)


if __name__ == "__main__":
    tf.app.run()
