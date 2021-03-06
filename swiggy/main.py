import requests
from bs4 import BeautifulSoup 
from restaurants import Restaurant
import json
import threading
import dish
from dish import Dish
from dynamodb_batch_write import DynamoDBBatchWrite
from write_to_s3_parquet import WriteS3Parquet
import time
import os


class Swiggy:

    def __init__(self):
        self.CONFIG_FILE = "jwt-config.json"
        with open(self.CONFIG_FILE,'r') as config_file:
            self.data_set = json.load(config_file)

        self.starter_config = self.data_set['SWIGGY']['CONFIG']['STARTER']

        self.config = self.data_set['SWIGGY']['CONFIG']
        self.dishes_data = []
        self.restaurants_data = []
        self.restaurants_obj = Restaurant(self.config)
        self.city = os.getenv('CITY', "jaipur")
        self.country = os.getenv('COUNTRY', "india")
        self.city_code = self.city+'__'+self.country
        self.dish_obj = Dish(self.config, self.city, self.country, self.city_code)
        
        

    def get_data(self, url=None):

        print('+++++++IT WILL RUN')
        
        URL = self.starter_config["URLS"]['jaipur']
        r = requests.get(URL) 


        soup = BeautifulSoup(r.content, 'html5lib')

        TAG = self.starter_config['SELECTORS']['WAIT']['TAG']
        FIND_BY = self.starter_config['SELECTORS']['WAIT']['FIND_BY']
        VALUE = self.starter_config['SELECTORS']['WAIT']['VALUE'] 
        data = soup.find_all(TAG,attrs={FIND_BY:VALUE})


        _list = []
        for row in data:
            link = row['href']
            subzone = row.text
            _list.append({
                'subzone': subzone,
                'link':"https://www.swiggy.com"+link
            })

        
        no_of_threads = 3
        last_chunk = -1
        subzone_batch_threads = []
        length_of_subzones = len(_list)
        chunk_size = int(length_of_subzones/no_of_threads)
        print('************chunk size',chunk_size)

        if length_of_subzones >= no_of_threads: 
            for i in range(no_of_threads):
                
                batch = _list[i*chunk_size:(i+1)*chunk_size]
                # batch = _list[0:1]
                subzone_batch_threads.append(threading.Thread(
                            target=self.get_restaurants_thread, args=(batch,)))
                subzone_batch_threads[-1].start()
                last_chunk = i

            last_chunk += 1
            if no_of_threads*chunk_size < length_of_subzones:
                
                batch = _list[last_chunk*chunk_size:length_of_subzones]
                # batch = _list[0:1]
                subzone_batch_threads.append(threading.Thread(
                            target=self.get_restaurants_thread, args=(batch,)))
                subzone_batch_threads[-1].start()


            for thread in subzone_batch_threads:
                print('\n\n**************JOINING***********')
                thread.join()
        else:
            for subzone in _list:
                self.restaurants_obj.get_restaurants(subzone['link'],subzone['subzone'],self.restaurants_data)

        self.get_dishes()
        print('++++DISHES LEN', len(self.dishes_data))

        # load data to dynamodb
        self.dynamodb_batch_write_obj = DynamoDBBatchWrite()
        self.dynamodb_batch_write_obj.batch_write_to_ddb(self.dishes_data)
        
        for dish_data in self.dishes_data:
            dish_data['stars'] = float(dish_data['stars'])

        # write data to parquet in s3
        self.write_to_s3_parquet_obj = WriteS3Parquet(self.city)
        self.write_to_s3_parquet_obj.write_to_parquet(self.dishes_data)
        

    def get_restaurants_thread(self, subzones):
        print('+++++=THREAD')
        for subzone in subzones:
            self.restaurants_obj.get_restaurants(subzone['link'],subzone['subzone'],self.restaurants_data)

    def get_dishes(self):
        no_of_threads = 3
        last_chunk = -1
        restaurant_batch_threads = []
        length_of_restaurants_data = len(self.restaurants_data)
        chunk_size = int(length_of_restaurants_data/no_of_threads)
        for i in range(no_of_threads):
            
            batch = self.restaurants_data[i*chunk_size:(i+1)*chunk_size]
            # batch = restaurants_data[0:2]
            restaurant_batch_threads.append(threading.Thread(
                        target=self.get_dishes_thread, args=(batch,)))
            restaurant_batch_threads[-1].start()
            last_chunk = i

        last_chunk += 1
        if no_of_threads*chunk_size < length_of_restaurants_data:
            
            batch = self.restaurants_data[last_chunk*chunk_size:length_of_restaurants_data]
            # batch = restaurants_data[0:2]
            restaurant_batch_threads.append(threading.Thread(
                        target=self.get_dishes_thread, args=(batch,)))
            restaurant_batch_threads[-1].start()

        for thread in restaurant_batch_threads:
            thread.join()

    def get_dishes_thread(self, restaurants):

        for restaurant in restaurants:
            self.dish_obj.get_details(restaurant,self.dishes_data)


    
if __name__ == '__main__':
    start = time.time()
    swiggy = Swiggy()
    swiggy.get_data()
    end = time.time()
    print('++++++++++TIME CONSUME',end-start)