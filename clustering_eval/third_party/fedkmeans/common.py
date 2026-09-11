import numpy as np
import os
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.metrics.cluster import rand_score, adjusted_rand_score
import matplotlib.pyplot as plt


def load_data(i, dset, beta = None, ppc = 100, noise = 1):
    # cwd = os.getcwd()
    cwd = os.path.dirname(os.path.realpath(__file__))
    if dset == "regular":
        datafile = cwd + "/data/beta" + str(beta) + "/cluster_beta" + str(beta) + "_client" + str(i) + ".csv" 
        labelfile = cwd + "/data/beta" + str(beta) + "/labels_beta" + str(beta) + "_client" + str(i) + ".csv" 
    elif dset == "super_diag":
        datafile = cwd + "/data/super_diag/cluster_super_diag_beta1e-5_client" + str(i) + ".csv"
        labelfile = cwd + "/data/super_diag/labels_super_diag_beta1e-5_client" + str(i) + ".csv"
    elif dset == "cluster_wise":
        datafile = cwd + "/data/cluster_wise_small/cluster_wise_client" + str(i) + ".csv"
        labelfile = cwd + "/data/cluster_wise_small/labels_cluster_wise_client" + str(i) + ".csv"
    elif dset == "abl":
        datafile = cwd + "/data/beta" + str(beta) + "/cluster_beta" + str(beta) + "_ppc" + str(ppc) + "_noise" + str(noise) + "_client" + str(i) + ".csv"         
        labelfile = cwd + "/data/beta" + str(beta) + "/labels_beta" + str(beta) + "_ppc" + str(ppc) + "_noise" + str(noise) + "_client" + str(i) + ".csv"         
    elif dset == "FEMNIST":
        datafile = cwd + "/data/MNIST/MNIST_cluster_client" + str(i) + ".csv"
    elif dset == "cancer_iid":
        datafile = cwd + "/data/fourcancers/client" + str(i) + "_iid_Tumor_PCA.csv"
    elif dset == "cancer_niid":
        datafile = cwd + "/data/fourcancers/client" + str(i) + "_niid_Tumor_PCA.csv"


    data = np.genfromtxt(datafile, delimiter=',')
    if dset == "FEMNIST" or dset == "cancer_iid" or dset == "cancer_niid":
        labels = None
    else:
        labels = np.genfromtxt(labelfile, delimiter=',') 
    
    return data, labels

def det_n_clients(dset):
    if dset == "FEMNIST":
        return 10
    elif dset == "cancer_iid" or dset == "cancer_niid" :
        return 3
    else:
        return 5
    
def load_config(dset = 'abl', n_runs = 1, crounds = 10, k_global = 2, init = 'k-means++', iter_local = 1, drop = True, weighted_agg = True, dset_options = {}):
    config_options = {
        'dset' : ['abl', 'FEMNIST', 'cancer_iid', 'cancer_niid'],
        'n_runs' : [1, 200],
        'crounds' : [1, 100],
        'k_global' : [2, 100],
        "n_clients" : [2, 50],
        "init" : ['k-means++', 'random'],
        'iter_local' : [1, 100],
        "drop" : [True, False],
        "weighted_agg" : [True, False]
    }
    
    config = {
        'dset': dset,
        'n_runs': n_runs,
        'crounds': crounds,
        'k_global': k_global,
        'n_clients': det_n_clients(dset),
        'init' : init,
        'iter_local' : iter_local,
        'drop' : drop,
        'weighted_agg' : weighted_agg
        }


    # assert correctly loaded config
    for key in config.keys():
        if type(config[key]) == int:
            assert (config[key] >= min(config_options[key])) and (config[key] <= max(config_options[key])), f"value for {key} out of bounds: {config[key]}. Minimum: {min(config_options[key])}, maximum: {max(config_options[key])}." 
        elif type(config[key]) == str or type(config[key] == bool):
            assert config[key] in config_options[key], f'invalid value for {key}: config[key]. options: {config_options[key]}.'
        else:
            AssertionError(f"unkown type for {key}: {type(key)}.")
    
    # we assert these beforehand
    for key in dset_options:
        config[key] = dset_options[key]


    return config


def load_dset_config(ppc = 50, noise = 1, beta = 1):
    config_options = {
        "ppc" : [50, 100, 200],
        "noise" : [1, 1.1, 1.2, 1.3, 1.4, 1.5],
        "beta" : [0.1, 1, 10]
    }

    config= {
        "ppc" : ppc,
        "noise" : noise,
        "beta" : beta}
    
    for key in config.keys():
        assert config[key] in config_options[key], f'unkown value for {key} : {config[key]}. options: {config_options[key]}'

    return config



# (CENTRAL) method to calculate silhouette scores
def calc_silhouette_score(dset, centers):

    km = KMeans(n_clusters = centers.shape[0])#.fit(dset)
    km.cluster_centers_ = np.copy(centers)
    km._n_threads = 8
    labels = km.predict(dset)
    score = silhouette_score(dset, labels)
    return score


def calc_ssilh_score_fed2(clients, centers):
    
    cluster_averages = []
    cluster_sizes = []

    global_cluster_averages = np.zeros_like(centers)
    total_sizes = np.zeros((centers.shape[0],1))
    for client in clients:
        cluster_average, cluster_size = client.get_cluster_averages(centers)
        cluster_size = cluster_size.reshape(-1, 1)        

        global_cluster_averages += cluster_average * cluster_size
        total_sizes += cluster_size

    global_cluster_averages /= total_sizes
        #cluster_averages.append(cluster_average)
        #cluster_sizes.append(cluster_size)
        #global_cluster_averages
    
    #cluster_avgs = np.array(cluster_averages)	
    #print(f'cluster_avgs shape: {cluster_avgs.shape}')
    #print(f'local cluster averages of last client: {cluster_average}')
    #print(f'global cluster average: {global_cluster_averages}')
    
    #global_cluster_averages = weighted_avg(cluster_averages, cluster_sizes)

    return(calc_simpl_silh_score_fed(clients, global_cluster_averages))

def calc_simpl_silh_score_fed(clients, global_centers):
    
    local_scores = np.zeros((len(clients), 1))
    local_sizes = np.zeros(len(clients))

    for i, client in enumerate(clients):
        local_scores[i,:], local_sizes[i] = client.calc_local_ssilh_score(global_centers)
    
    global_score = weighted_avg(local_scores, local_sizes)

    return global_score

def calc_ssilh_score2(dsets, centers):
    full_dset = np.vstack(dsets)

    km = KMeans(n_clusters = centers.shape[0])
    km.cluster_centers_ = np.copy(centers)
    km._n_threads = 8
    labels = km.predict(full_dset)

    cluster_means = np.zeros_like(centers)
    for i, label in enumerate(np.unique(labels)):
        #print(full_dset[labels == label,...].shape)
        cluster_means[i,...] = np.mean(full_dset[labels == label,...], axis = 0)
        
    #print(cluster_means.shape)

    score = 0
    for i, label in enumerate(labels):
        #print(point.shape)
        ai = np.linalg.norm(full_dset[i,...] - cluster_means[label,...])
        bi = np.min(np.linalg.norm(full_dset[i,...] - cluster_means[np.arange(centers.shape[0]) != label, ...], axis = 1))
        score_i = (bi - ai)/max(bi, ai)
        score += score_i
    score /= full_dset.shape[0]
    return score

# this is for now stuffed in one function, but can easily made "federated"
def calc_simpl_silh_score(dsets, centers):
    score = 0
    for dset in dsets:
        km = KMeans(n_clusters = centers.shape[0])
        km.cluster_centers_ = np.copy(centers)
        km._n_threads = 8
        labels = km.predict(dset)
        
        for i, label in enumerate(labels):            
            bi = np.min(np.linalg.norm(dset[i,:] - centers[np.arange(centers.shape[0]) != label,:], axis = 1))
            ai = np.linalg.norm(dset[i,:] - centers[label,:])
            score_i = (bi - ai)/(max(bi, ai))
            score += score_i
    score /= sum([dset.shape[0] for dset in dsets])
    return score

def stack_data(datasets, labels):
    data_full = np.vstack(datasets)
    
    if None in labels:
       labels_full = None 
    else:
        labels_full = np.concatenate(labels)
        
    '''
    for i ,(data, label) in enumerate(zip(datasets, labels)):
        if i == 0:
            data_full = data
            labels_full = label
        else:
            data_full = np.concatenate((data, data_full), axis = 0)
            labels_full = np.concatenate((label, labels_full), axis=0)
    '''
    return data_full, labels_full


def load_stacked_data(dset_id, n_clients, beta = None, ppc = 100, noise = 1):
    dsets = []
    labels = []
    for i in range(n_clients):
        dset, label = load_data(i, dset_id, beta = beta, ppc = ppc, noise = noise)
        dsets.append(dset)
        labels.append(label)
        
    return(stack_data(dsets, labels))


def weighted_avg(scores, dset_sizes):
    tot_samples = 0
    avg_scores = np.zeros(scores.shape[1])

    for dset_i, size in enumerate(dset_sizes):
        avg_scores += size * scores[dset_i, :]
        tot_samples += size

    avg_scores /= tot_samples
    return avg_scores
    

def calc_ARI(centers, datasets, labels):

    km = KMeans(n_clusters = len(centers), init = centers)
    #I still don't like this hack but seems like I have to
    km.fit(datasets[0])
    km.cluster_centers_ = np.copy(centers)
    
    scores = np.zeros(len(datasets))
    
    for i, (dataset, label) in enumerate(zip(datasets, labels)):
        pred = km.predict(dataset)
        scores[i] = adjusted_rand_score(label, pred)

    return scores

def plot_federated(data_full, means_true, means_est, title= None):
        # make an extra 'kmeans' object for visualization
    s = 0

    server_kmeans = KMeans(n_clusters=17).fit(data_full) #need fit before predict (small hack)
    server_kmeans.cluster_centers_ = np.copy(means_est)# overwrite the 'fit' results

    predict_labels = server_kmeans.predict(data_full) #these are used for visualization

    colors = ['b', 'g', 'c', 'm', 'y', 'orange', 'brown',
              'pink', 'navy', 'lightsteelblue', 'bisque', 'yellow', 'lightgreen', 'violet', 'sandybrown', 'slategrey', 'black']


    
    for point_i in range(data_full.shape[0]):
        plt.plot(data_full[point_i,0], data_full[point_i,1],'.', color=colors[predict_labels[point_i]])

    plt.plot(means_true[0,:], means_true[1,:], 'o', color="black", label="true")

    #plt.plot(means_original[0,:], means_original[1,:],"o", color="black", label = "true")
    plt.plot(means_est[:,0], means_est[:,1], "X", color="red", label="estimated")
    plt.legend()
    plt.xlabel("$X_1$")
    plt.ylabel("$X_2$")
    plt.title(title)
    plt.grid(True)
    #plt.savefig("federated_results2.eps", format="eps")
    
    
        
def plot_range(data, data2=None, line='-', color=None, label = None, convert = False):
    if data2 == None:
        x = np.arange(data.shape[1])
    else:
        x = np.mean(data2, axis =0)
    mean = np.mean(data, axis=0)
    std = np.std(data, axis=0)
    #std = np.var(data, axis=0)
    if color==None:
        ax,  = plt.plot(x, mean,line, label=label)
        plt.fill_between(x, mean-std, mean+std, alpha = 0.5)
    else:
        if convert:
            r,g,b,a = c.to_rgba(color, alpha = 0.5)
#alpha = 0.5
            r_new = ((1 - a) * 1) + (a * r)
            g_new = ((1 - a) * 1) + (a * g)
            b_new = ((1 - a) * 1) + (a * b)

            ax = plt.plot(x, mean, line, color=color, label=label)
            plt.fill_between(x, mean-std, mean+std, color = (r_new, g_new, b_new))
        else:
            ax = plt.plot(x, mean,line, color=color, label = label)
            plt.fill_between(x, mean-std, mean+std, alpha = 0.5, color=color)

    return ax
