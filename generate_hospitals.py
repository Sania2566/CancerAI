import pandas as pd
from geopy.geocoders import Nominatim
import time
import random

geolocator = Nominatim(user_agent="hospital_finder")

data = []

countries = {

"India":[
"Mumbai","Delhi","Bangalore","Chennai","Kolkata","Hyderabad","Pune","Ahmedabad","Jaipur","Lucknow",
"Chandigarh","Patna","Bhopal","Indore","Surat","Nagpur","Amritsar","Kanpur","Varanasi","Coimbatore"
],

"USA":[
"New York","Los Angeles","Chicago","Houston","Phoenix","Philadelphia","San Antonio","San Diego",
"Dallas","San Jose","Austin","Jacksonville","Fort Worth","Columbus","Charlotte","San Francisco",
"Indianapolis","Seattle","Denver","Boston"
],

"UK":[
"London","Manchester","Birmingham","Leeds","Liverpool","Sheffield","Bristol","Leicester","Nottingham",
"Coventry","Reading","Oxford","Cambridge","Derby","Brighton","York","Bath","Glasgow","Edinburgh","Cardiff"
],

"Canada":[
"Toronto","Montreal","Vancouver","Calgary","Ottawa","Edmonton","Winnipeg","Quebec City","Hamilton",
"Kitchener","London","Victoria","Halifax","Oshawa","Windsor","Saskatoon","Regina","Barrie","Kelowna","Guelph"
],

"Australia":[
"Sydney","Melbourne","Brisbane","Perth","Adelaide","Canberra","Hobart","Darwin","Gold Coast",
"Newcastle","Wollongong","Geelong","Townsville","Cairns","Toowoomba","Ballarat","Bendigo",
"Launceston","Mackay","Rockhampton"
],

"Germany":[
"Berlin","Hamburg","Munich","Cologne","Frankfurt","Stuttgart","Dusseldorf","Dortmund","Essen","Leipzig",
"Bremen","Dresden","Hanover","Nuremberg","Bonn","Karlsruhe","Mannheim","Augsburg","Wiesbaden","Bochum"
],

"France":[
"Paris","Marseille","Lyon","Toulouse","Nice","Nantes","Strasbourg","Montpellier","Bordeaux","Lille",
"Rennes","Reims","Le Havre","Saint Etienne","Toulon","Grenoble","Dijon","Angers","Nimes","Clermont"
],

"Japan":[
"Tokyo","Osaka","Yokohama","Nagoya","Sapporo","Kobe","Kyoto","Fukuoka","Kawasaki","Hiroshima",
"Sendai","Kitakyushu","Chiba","Sakai","Niigata","Hamamatsu","Okayama","Kumamoto","Kagoshima","Nagasaki"
],

"Brazil":[
"Sao Paulo","Rio de Janeiro","Brasilia","Salvador","Fortaleza","Belo Horizonte","Manaus","Curitiba",
"Recife","Porto Alegre","Goiania","Belem","Campinas","Sao Luis","Maceio","Natal","Teresina","Aracaju","Cuiaba","Florianopolis"
],

"South Africa":[
"Johannesburg","Cape Town","Durban","Pretoria","Port Elizabeth","Bloemfontein","East London",
"Polokwane","Kimberley","Nelspruit","Pietermaritzburg","George","Welkom","Klerksdorp","Rustenburg",
"Uitenhage","Vereeniging","Brakpan","Benoni","Tzaneen"
]

}

for country, cities in countries.items():

    for city in cities:

        location = geolocator.geocode(f"{city}, {country}")

        if location:

            lat = location.latitude
            lon = location.longitude

            data.append({
                "name": f"{city} Cancer Hospital",
                "city": city,
                "country": country,
                "rating": round(random.uniform(4.2,4.9),1),
                "latitude": lat,
                "longitude": lon
            })

            print("Added:",city,country)

        time.sleep(1)


df = pd.DataFrame(data)

df.to_csv("data/hospitals.csv",index=False)

print("Dataset created successfully!")