import numpy as np
from sklearn.cluster import KMeans, kmeans_plusplus
from sklearn.metrics.cluster import adjusted_rand_score
from common import *
from tqdm import tqdm








class client_FKM():
    def __init__(self, data, labels, n_clusters, drop_empty_clusters = True, n_iter = 1, init = "k-means++") : 
        self.data = data
        self.labels = labels #ground-truth labels; purely used for validation
        self.n_clusters = min(data.shape[0], n_clusters)
        self.n_iter = n_iter
        self.init = init
        self.drop = drop_empty_clusters
        self.means, self.sample_amts = self.init_means()
        

    def init_means(self):
        # local_clusters, _ = kmeans_plusplus(self.data, self.n_clusters)
        km = KMeans(n_clusters = self.n_clusters, max_iter = self.n_iter, init = self.init).fit(self.data)
        # km.cluster_centers_ = np.copy(local_clusters)
        local_clusters = np.copy(km.cluster_centers_)

        labels = km.predict(self.data)
        sample_amts = np.array([len(labels[labels == i]) for i in range(self.n_clusters)])
        
        cluster_mask = [sample > 1 for sample in sample_amts]
        local_clusters = local_clusters[cluster_mask]
        sample_amts = sample_amts[cluster_mask]


        return local_clusters, sample_amts
    
    def det_local_clusters(self):
        scores = self.det_score()
        if self.drop:
            self.discard_empty_clusters()
        sample_amts = self.km_local()
        return np.copy(self.means),  sample_amts, scores

    def det_score(self):
        self.n_clusters = self.means.shape[0]
        km = KMeans(n_clusters = min(self.data.shape[0], self.n_clusters), max_iter = 1).fit(self.data)

        # need to 'unfit' the data
        #km.n_clusters_ = self.n_clusters
        km.cluster_centers_ = np.copy(self.means)

        cluster_labels = km.predict(self.data)  
        
        if self.labels is None:
            score = None
        else:
            score = adjusted_rand_score(self.labels, cluster_labels)
            
        return score
    
    def discard_empty_clusters(self):
        self.n_clusters = self.means.shape[0]
        # we're running fit only to avoid errors (sklearn doesn't like modifying unfitted classifiers)
        km = KMeans(n_clusters = min(self.data.shape[0], self.n_clusters)).fit(self.data)

        # need to 'unfit' the data
        km.cluster_centers_ = np.copy(self.means)

        #assign data to clusters
        cluster_labels = km.predict(self.data)  
        
        # check which clusters are empty
        non_empty_clusters = [ np.where(cluster_labels == i)[0].shape[0] > 0 for i in range(self.n_clusters)]    
        
        # discard empty clusters & determine new k_local (n_clusters)
        self.means = self.means[non_empty_clusters]
        self.n_clusters = len(self.means)



    def km_local(self):
        km = KMeans(n_clusters = self.n_clusters, init = self.means, max_iter = self.n_iter, n_init = 1).fit(self.data)
        self.means = np.copy(km.cluster_centers_)
        sample_amts = np.array([len(km.labels_[km.labels_ == i]) for i in range(self.n_clusters)])
        
        # assert clusters are larger than size 1 (privacy issues)
        cluster_mask = [sample > 1 for sample in sample_amts]
        self.means = self.means[cluster_mask]
        sample_amts = sample_amts[cluster_mask]
        #print(self.data.shape[0], self.n_clusters, sample_amts)

        return(sample_amts)
    

    def get_cluster_averages(self, cluster_centers):

        km = KMeans(n_clusters = cluster_centers.shape)
        km.cluster_centers_ =  np.copy(cluster_centers)
        km._n_threads = 8

        labels = km.predict(self.data)

        cluster_means = np.zeros_like(cluster_centers)
        cluster_sizes = np.zeros(cluster_centers.shape[0])

        for i, label in enumerate(np.unique(labels)):
            cluster_means[i,...] = np.mean(self.data[labels == label, ...], axis = 0)
            cluster_sizes[i] = self.data[labels == label, ...].shape[0]
        
        return cluster_means, cluster_sizes
    
    def calc_local_ssilh_score(self, global_centers):
        km = KMeans(n_clusters = global_centers.shape[0])
        km.cluster_centers_ = np.copy(global_centers)
        km._n_threads = 8
        labels = km.predict(self.data)
        score = 0
        for i, label in enumerate(labels):
            bi = np.min(np.linalg.norm(self.data[i,:] - global_centers[np.arange(global_centers.shape[0]) != label, :], axis = 1))
            ai = np.linalg.norm(self.data[i,:] - global_centers[label,:])
            score_i = (bi - ai)/max(bi,ai)
            score += score_i   
        score /= self.data.shape[0]

        return score, self.data.shape[0] 


class server_FKM():
    def __init__(self, n_global, weighted = True):
        self.n_global = n_global
        self.weighted = weighted
        
    def aggregate(self, local_clusters, samples):
        cluster_aggregator = KMeans(n_clusters = self.n_global)
        avg_means = np.zeros((self.n_global, 2))

        means_res = np.array(local_clusters)
        #cluster_aggregator.fit(means_res, sample_weight =  samples.reshape(-1))
        if self.weighted == True:
            cluster_aggregator.fit(means_res, sample_weight = samples)
        else:
            cluster_aggregator.fit(means_res)
        return cluster_aggregator.cluster_centers_




def load_clients(config):
    # initialize clients, including first versions for cluster means (using k_global)
    local_clusters = []
    clients = []

    cluster_sizes = []
    for i in range(config['n_clients']):
        data, labels = load_data(i, config['dset'], beta=config['beta'], ppc = config['ppc'], noise=config['noise'])
        client = client_FKM(data, labels, config['k_global'], n_iter=config['iter_local'], drop_empty_clusters=config['drop'], init=config['init'])
        clients.append(client)
        local_clusters.append(client.means)
        cluster_sizes.append(client.sample_amts)

    local_clusters = np.concatenate(local_clusters)
    cluster_sizes = np.concatenate(cluster_sizes)

    return clients, local_clusters, cluster_sizes



def run(config):

    crounds = config['crounds']
    n_runs = config['n_runs']
    k_global = config['k_global']
    n_clients = config['n_clients']

    scores = np.zeros((n_clients, crounds, n_runs))
    avg_scores = np.zeros((crounds, n_runs))

    for r in range(n_runs):
        local_clusters = []
        clients = []

        cluster_sizes = []

        # create server object
        server = server_FKM(k_global, weighted=config['weighted_agg'])

        # initialize clients
        clients, local_clusters, cluster_sizes = load_clients(config)

        for c in range(crounds):
            # aggregate local clusters into global clusters
            global_clusters = server.aggregate(local_clusters, cluster_sizes)

            local_clusters = []
            cluster_sizes = []
            # for each client, do:
            for i, client in enumerate(clients):
                # "send" global clusters to clients
                client.means = np.copy(global_clusters)
                # determine which clusters are empty & run kmeans locally for new local clustering
                local_cluster, cluster_size, scores[i,c,r] = client.det_local_clusters()
                
                #append to data structures
                local_clusters.append(local_cluster)
                cluster_sizes.append(cluster_size)

            local_clusters = np.concatenate(local_clusters)
            cluster_sizes = np.concatenate(cluster_sizes)

        # for FEMNIST, we look at silhouette score (centrally calcualted)        
        if (config['dset'] in ["FEMNIST", "cancer_iid", "cancer_niid"]):
            full_dset, _ = load_stacked_data(config['dset'], n_clients)
            avg_scores[0,r] = calc_silhouette_score(full_dset, global_clusters)
            avg_scores[1,r] = calc_ssilh_score_fed2(clients, global_clusters)

    # combine ARI into (weighted) mean ARI for all clients combined
    if (config['dset'] not in ["FEMNIST", "cancer_iid", "cancer_niid"]):
        tot_samples = 0
        #fed_mean = np.zeros(n_runs)
        for client_i, client_o in enumerate(clients):
            n_s = len(client_o.labels)
            avg_scores += n_s * scores[client_i, :, :]
            tot_samples += n_s
        avg_scores /= tot_samples

    return avg_scores





# def run_V2(n_global,n_runs = 1, crounds = 10, beta = 0.1, dset = 'regular', ppc = 50, noise = 1 ):
    
#     if (dset == "FEMNIST"):
#         n_clients = 10
#         fed_score = False
#     else:
#         n_clients = 5
#         fed_score = True

#     scores = np.zeros((n_clients, crounds, n_runs))
#     avg_scores = np.zeros((crounds, n_runs))
#     for r in tqdm(range(n_runs)):
#         local_clusters = []
#         clients = []

#         cluster_sizes = []

#         # create server object
#         server = server_V2(n_global)

#         # initialize clients, including first versions for cluster means (using n_global)
#         for i in range(n_clients):
#             data, labels = load_data(i, dset, beta=beta, ppc = ppc, noise=noise)
#             client = client_V2(data, labels, n_global)
#             clients.append(client)
#             local_clusters.append(client.means)
#             cluster_sizes.append(client.sample_amts)

#         local_clusters = np.concatenate(local_clusters)


#         cluster_sizes = np.concatenate(cluster_sizes)

#         #print(cluster_sizes)
#         for c in range(crounds):
#             #print("round:" , c)
#             global_clusters = server.aggregate(local_clusters, cluster_sizes)

#             local_clusters = []
#             cluster_sizes = []
#             for i, client in enumerate(clients):
#                 #client.set_clusters(global_clusters)
#                 client.means = np.copy(global_clusters)
#                 client.n_clusters = global_clusters.shape[0]
#                 local_cluster, cluster_size, scores[i,c,r] = client.det_local_clusters(score = fed_score)
#                 local_clusters.append(local_cluster)
#                 cluster_sizes.append(cluster_size)

#             local_clusters = np.concatenate(local_clusters)
#             cluster_sizes = np.concatenate(cluster_sizes)

#     # for FEMNIST, we look at silhouette score (centrally calcualted)        
#         if (dset == "FEMNIST"):
#             full_dset, _ = load_stacked_data(dset, n_clients)
#             avg_scores[0,r] = calc_silhouette_score(full_dset, global_clusters)
        
#     # calculate the (weighted) mean ARI for all clients combined
#     if (dset != "FEMNIST"):
#         tot_samples = 0
#         #fed_mean = np.zeros(n_runs)
#         for client_i, client_o in enumerate(clients):
#             n_s = len(client_o.labels)
#             avg_scores += n_s * scores[client_i, :, :]
#             tot_samples += n_s

#         avg_scores /= tot_samples
#     return(avg_scores)
