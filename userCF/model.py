import pandas as pd
import pickle
import os
import csv
from math import sqrt
from .user import User
from .item import Item


class UserCF(object):
    def __init__(self, all_user_id, k, n, ensure_new=True):
        """pass unique id for users and items
           k is the number of the most similar users to take into account
           n is the number of the most suitable items to be recommend
        """
        self.users, self.items = {}, {}
        # init 'matrix', using dict rather than list of list
        # so that the user_id is not ristricted to be 0~len(users)-1
        self.user_sim_matrix = {int(user_id): {} for user_id in all_user_id}
        self.k = k
        self.n = n
        self.ensure_new = ensure_new

    def form_item_objects(self, event_data):
        """init item object for each item, and record
           unique users who touched this item
           count user's unique items at the same time
        """
        for index, row in event_data.iterrows():
            user_id, item_id = int(row['visitorid']), int(row['itemid'])
            # find if the item and user has been created
            try:
                self.items[item_id].covered_users.add(user_id)
            except KeyError:
                item = Item(item_id)
                item.covered_users.add(user_id)
                self.items[item_id] = item
            try:
                self.users[user_id].covered_items.add(item_id)
            except KeyError:
                user = User(user_id)
                user.covered_items.add(item_id)
                self.users[user_id] = user

    def update_user_count_dict(self, user_A_id, user_B_id):
        """find user_A's count dict in the sim matrix,
           update the dict by add 1 to the value of user_B
        """
        try:
            count_dict = self.user_sim_matrix[user_A_id]
        except KeyError:
            count_dict = self.user_sim_matrix[user_A_id] = {}  # all reference
        try:
            count_dict[user_B_id] += 1
        except KeyError:
            count_dict[user_B_id] = 1

    def form_users_distance_matrix(self, event_data, metric):
        # only consider 'transaction' and 'add to chart' action,
        # for retailrocket data set which is 3 or 2
        bool_index = event_data['event'] != 1
        event_data = event_data.loc[bool_index, :]
        self.form_item_objects(event_data)
        # update user-user common items counts
        for item in self.items.values():
            users = list(item.covered_users)  # convert to list for indexing
            # iter through all user pairs
            for i in range(len(users)-1):
                for j in range(i+1, len(users)):
                    user_A_id, user_B_id = users[i], users[j]
                    self.update_user_count_dict(user_A_id, user_B_id)
                    self.update_user_count_dict(user_B_id, user_A_id)
        # divide counts
        for user_id, count in self.user_sim_matrix.items():  # count is reference
            try:
                all_count = len(self.users[user_id].covered_items)
            except KeyError:
                # the user which comes from the full set,
                # not in test set, so make it remain empty
                continue
            for another_user_id in count.keys():
                another_user = self.users[another_user_id]
                all_count_another = len(another_user.covered_items)
                count[another_user_id] /= sqrt(all_count*all_count_another)
                assert count[another_user_id] <= 1

    def save(self, dir):
        with open(os.path.join(dir, 'users.pickle'), 'wb') as f:
            f.write(pickle.dumps(self.users))
        with open(os.path.join(dir, 'items.pickle'), 'wb') as f:
            f.write(pickle.dumps(self.items))
        with open(os.path.join(dir, 'user_sim_matrix.pickle'), 'wb') as f:
            f.write(pickle.dumps(self.user_sim_matrix))

    def load(self, dir):
        with open(os.path.join(dir, 'users.pickle'), 'rb') as f:
            self.users = pickle.loads(f.read())
        with open(os.path.join(dir, 'items.pickle'), 'rb') as f:
            self.items = pickle.loads(f.read())
        with open(os.path.join(dir, 'user_sim_matrix.pickle'), 'rb') as f:
            self.user_sim_matrix = pickle.loads(f.read())

    def rank_potential_items(self, target_user_id, related_users_id):
        """rank score's range is (0, +inf)
        """
        items_rank = {}
        target_user = self.users[target_user_id]
        for user_id in related_users_id:
            similar_user = self.users[user_id]
            similarity = self.user_sim_matrix[target_user_id][user_id]
            for item_id in similar_user.covered_items:
                if self.ensure_new and (item_id in target_user.covered_items):
                    continue  # skip item that already been bought
                score = similarity * 1
                try:
                    items_rank[item_id] += score
                except KeyError:
                    items_rank[item_id] = score
        return items_rank

    def get_top_n_items(self, items_rank):
        items_rank = sorted(items_rank.items(), key=lambda item: item[1],
                            reverse=True)
        items_id = [x[0] for x in items_rank]
        if len(items_id) < self.n:
            return items_id
        return items_id[:self.n]

    def make_recommendation(self, user_id):
        try:
            target_user = self.users[user_id]
            # find the top k users that most like the input user
            related_users = self.user_sim_matrix[user_id]
            if len(related_users) == 0:
                print('user {} didn\'t has any common item with other users')
                return -1
            related_users = sorted(related_users.items(),
                                   key=lambda item: item[1],
                                   reverse=True)  # return a list of tuples
            if len(related_users) >= self.k:
                related_users_id = [x[0] for x in related_users[:self.k]]
            else:
                related_users_id = [x[0] for x in related_users]
            items_rank = self.rank_potential_items(user_id, related_users_id)
            assert len(items_rank) > 0
            if self.ensure_new and len(items_rank) == 0:
                print('All recommend items has already been bought by the user.')
                return -3
            return self.get_top_n_items(items_rank)
        except KeyError:
            print('User {} has not shown in the training set.')
            return -2

    def compute_n_hit(self, user_id, real_items):
        # see what items we will recommend to this user
        recommend_items = self.make_recommendation(user_id)
        if not isinstance(recommend_items, list):
            # print('Cannot make recommendation for this user with error code: {}'.format(recommend_items))  # noqa
            return -1
        # count hit
        n_hit = 0
        for item_id in real_items:
            if item_id in recommend_items:
                n_hit += 1
        return n_hit, recommend_items

    def evaluate(self, test_data):
        """compute recall, precision and coverage
        """
        users_id = pd.unique(test_data['visitorid'])
        total_recall = 0
        total_precision = 0
        n_valid_users = 0
        covered_items = set()
        for user_id in users_id:
            # get user's real interested items id
            boolIndex = test_data['visitorid'] == user_id
            user_data = test_data.loc[boolIndex, :]
            real_items = pd.unique(user_data['itemid'])
            try:
                n_hit, reco_items = self.compute_n_hit(user_id, real_items)
            except TypeError:
                continue
            # recall
            recall = n_hit/len(real_items)
            total_recall += recall
            # precision
            precision = n_hit/len(reco_items)
            total_precision += precision
            n_valid_users += 1
            # coverage
            covered_items.update(reco_items)
        recall = total_recall/n_valid_users
        precision = total_precision/n_valid_users
        coverage = len(covered_items)/len(self.items.keys())
        print('number of valid unique users: {}'.format(n_valid_users))
        print('total unique users in the test set: {}'.
              format(len(pd.unique(test_data['visitorid']))))
        return {'recall': recall, 'precision': precision, 'coverage': coverage}


def train_user_fc_model(portion, event_data_path, model_save_dir):
    event_data = pd.read_csv(event_data_path)
    # use small set for limited memory
    event_data = event_data.iloc[:int(len(event_data)*portion), :]
    split = int(len(event_data)*0.8)
    train = event_data.iloc[:split, :]
    users_id = pd.unique(train['visitorid'])
    items_id = pd.unique(train['itemid'])
    model = UserCF(users_id, 80, 20, ensure_new=True)
    model.form_users_distance_matrix(train, metric='cosine')
    model.save(model_save_dir)


def evaluate_user_fc_model(portion, event_data_path, model_save_dir,
                           k, n, ensure_new):
    model = UserCF([], k, n, ensure_new)  # init an empty model with k
    model.load(model_save_dir)  # load pre-trained model data
    event_data = pd.read_csv(event_data_path)
    event_data = event_data.iloc[:int(len(event_data)*portion), :]
    bool_index = event_data['event'] != 1
    event_data = event_data.loc[bool_index, :]
    split = int(len(event_data)*0.8)
    test = event_data.iloc[split:, :]
    result = model.evaluate(test)
    # write result to file
    data_type = event_data_path.split('/')[1]
    with open('evaluation_results/userCF-{}.csv'.format(data_type),
              'a') as f:
        cols = ['k', 'n', 'recall', 'precision', 'coverage', 'ensure new']
        writer = csv.DictWriter(f, delimiter=',', fieldnames=cols)
        writer.writerow({'k': k, 'n': n,
                         'recall': result['recall'],
                         'precision': result['precision'],
                         'coverage': result['coverage'],
                         'ensure new': ensure_new})
