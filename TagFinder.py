import requests
from bs4 import BeautifulSoup
import sys

url_base = 'https://nhentai.net/tags/?page='

# with open('sauce_codes.txt', 'r') as file:
#     codes = file.readlines()
#     codes = [int(i) for i in codes]
#     codes.sort()
# if len(codes) > 0:
#     LastEntry = codes[-1]
# else:
#     LastEntry = 0

#Find total pages of tags

response = requests.get(url_base + '1')
soup = BeautifulSoup(response.text, 'html.parser')

lastPage = soup.find('a', class_='last').get('href')
lastPage = int(lastPage.split('=')[-1])


tags_container = soup.find('div', id='tag-container')
tags = tags_container.find_all('a')

Tag_tuple_list = []


for i in range(lastPage+1):
    url = url_base+str(i+1)
    try:
        response = requests.get(url)
        response.raise_for_status() # Check for HTTP request errors 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        tags_container = soup.find('div', id='tag-container')
        tags = tags_container.find_all('a')
        
        #Parse through
        for j in tags:
            temp = j.get('class')[-1]
            tag_code = int(temp.split('-')[-1])
            tag_name = j.find('span').text
            Tag_tuple_list.append((tag_code, tag_name))
       
        
           
       
           
    except requests.exceptions.HTTPError:
        #if count > LastEntry:
            #exit_loop += 1
        print(f'404 no website on {url}')
        break


with open("tags.txt", "w") as file:
    for tup in Tag_tuple_list:
        file.write(str(tup)+'\n')