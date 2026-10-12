import math
import numpy as np
from typing import List, Dict, Tuple, Callable
from scipy.spatial import distance

def get_all_neighbors(cell: tuple):
    # Compatibility/performance patch: the original builds all 3**d surrounding
    # combinations and then keeps only cells differing in exactly one coordinate.
    # Constructing those 2*d axial neighbors directly is mathematically identical
    # and avoids exponential memory/time growth on higher-dimensional datasets.
    neighbors = []
    for axis in range(len(cell)):
        lower = list(cell)
        lower[axis] -= 1
        neighbors.append(tuple(lower))
        upper = list(cell)
        upper[axis] += 1
        neighbors.append(tuple(upper))
    return neighbors

class FDBSCAN_Client():

    def initialize(self, params: Dict):
        self.__dataset = params['dataset']
        self.__L = params['L']
        self.__labels = []
        self.__true_labels = params['true_labels']
        self.__passive = True

    def get_dataset(self):
        return self.__dataset

    def get_labels(self):
        return self.__labels, self.__true_labels, self.__get_points()

    def is_passive(self):
        return self.__passive

    def __get_points(self, floor: bool = False):
        dimension = len(self.__dataset[0])
        points = []
        for row in self.__dataset:
            if floor:
                points.append(tuple(math.floor(row[i] / self.__L) for i in range(dimension)))
            else:
                points.append(tuple(row[i] for i in range(dimension)))
        return points

    def compute_local_update(self):

        self.__passive = False

        cells = np.array(self.__get_points(floor = True))
        dimensions = len(cells[0])

        max_cell_coords = []
        min_cell_coords = []
        for i in range(dimensions):
            max_cell_coords.append(np.amax(cells[:, i]))
            min_cell_coords.append(np.amin(cells[:, i]))

        shifts = np.zeros(dimensions)
        for i in range(dimensions):
            if min_cell_coords[i] < 0:
                shifts[i] = -1 * min_cell_coords[i]

        # Compatibility/performance patch: the original materializes a dense
        # d-dimensional count tensor whose size is the product of all cell ranges.
        # Only non-empty cells are ever returned, so a sparse dict computes exactly
        # the same contribution map without allocating the empty grid.
        dict_to_return = {}
        for cell in cells:
            key = tuple(int(value) for value in cell)
            dict_to_return[key] = dict_to_return.get(key, 0) + 1

        return dict_to_return

    def assign_points_to_cluster(self, cells: List, labels: List):

        points = self.__get_points()

        dense_cells = []
        for row in cells:
            dense_cells.append(tuple(row))

        while len(points) > 0:
            actual_point = points.pop(0)
            actual_cell = tuple(math.floor(actual_point[i] / self.__L) for i in range(len(actual_point)))
            outlier = True
            if actual_cell in dense_cells:
                self.__labels.append(labels[dense_cells.index(actual_cell)])
            else:
                min_dist = float('inf')
                cluster_to_assign = -1
                check_list = get_all_neighbors(actual_cell)
                for check_cell in check_list:
                    if check_cell in dense_cells:
                        cell_mid_point = tuple(cell_coord * self.__L + self.__L/2 for cell_coord in check_cell)
                        actual_dist = distance.euclidean(actual_point, cell_mid_point)
                        if actual_dist < min_dist:
                            min_dist = actual_dist
                            cluster_to_assign = labels[dense_cells.index(check_cell)]
                        outlier = False
                self.__labels.append(cluster_to_assign)

        self.__training_completed = True

class FDBSCAN_Server():

    def initialize(self, params: Dict):
        self.__MIN_POINTS = params['MIN_POINTS']
        self.__running = False

    def get_running(self):
        return self.__running

    def run(self, value: bool = True):
        self.__running = value

    def compute_clusters(self, contribution_map: Dict):

        key_list = list(contribution_map.keys())
        value_list = list(contribution_map.values())

        n_cells = len(key_list)
        visited = np.zeros(n_cells)
        clustered = np.zeros(n_cells)
        cells = []
        labels = []
        cluster_ID = 0

        while 0 in visited:
            curr_index = np.random.choice(np.where(np.array(visited) == 0)[0])
            curr_cell = key_list[curr_index]
            visited[curr_index] = 1

            num_points = value_list[curr_index]
            if num_points >= self.__MIN_POINTS:
                cells.append(curr_cell)
                labels.append(cluster_ID)
                clustered[curr_index] = 1

                list_of_cells_to_check = get_all_neighbors(curr_cell)
                while len(list_of_cells_to_check) > 0:
                    neighbor = list_of_cells_to_check.pop(0)
                    neighbor_index = key_list.index(neighbor) if neighbor in key_list else ""
                    if neighbor in key_list and visited[neighbor_index] == 0:
                        visited[neighbor_index] = 1
                        if value_list[neighbor_index] >= self.__MIN_POINTS:
                            list_of_cells_to_check += get_all_neighbors(neighbor)
                        if clustered[neighbor_index] == 0:
                            cells.append(neighbor)
                            labels.append(cluster_ID)
                            clustered[neighbor_index] = 1
                cluster_ID += 1

        return cells, labels
