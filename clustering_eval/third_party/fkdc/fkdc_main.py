from utils import *
import os
from sklearn.cluster import KMeans,DBSCAN
import matplotlib.pyplot as plt
import random
import numpy
from sklearn.metrics import silhouette_score, adjusted_rand_score, normalized_mutual_info_score
import time
'''
data2['full_data']=data
data2['true_label']=label
data2['num_clusters']=10
data2['order']=order
data2['eachlable']=allable
'''

dataname=['abalonefed','Aggregationfed','coil20fed','data_PenDigitsfed','Gesturefed','glassfed',
          'heartfed','jainfed','leaffed','liverfed','oliver400featurefed','Pathbasedfed',
          'R15fed','spambasefed','umistfed','uspsfed','vehiclefed','waveformfed','Yeastfed']

dataname=['Aggregationfed','Pathbasedfed','R15fed','waveformfed','abalonefed','jainfed','heartfed']
dataname=['glassfed','leaffed','Pathbasedfed','vehiclefed','Yeastfed']
dataname=['ecoli']
for i in dataname:
    start_time = time.time()
    data_path = '../dataset/'+i+'fed.pkl'
    datapkl = load_dataset(data_path)  # dataset is a json file
    print("Processing dataset:", data_path)
    print(datapkl['full_data'].shape)
    a=[]
    n=[]
    am=[]
    for iter in range(2000):
        ari, nmi,ami,parameters=results(data_path)
        a.append(ari)
        n.append(nmi)
        am.append(ami)
    print('ari',max(a),'nmi',max(n),'ami',max(am))
    end_time = time.time()
    print('number of centers in clients',parameters[0],'number of centers in servers',parameters[1],'k in SNN',parameters[2])
    print("运行时间：", end_time - start_time, "秒")


