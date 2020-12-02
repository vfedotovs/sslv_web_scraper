# About sslv_web_scraper application:
Purpouse: This application will parse information from ss.lv website from apartments for sale category in specific city of your choice
and  will send report filtered by your criteria to your gmail address 

# How to use application:
1. Update gmailer.py file with your email address and password
2. Buld and run basic docker image
```bash
docker build -t my-python-app .
docker run -it --rm --name my-running-app my-python-app
```
3. Report should arrive to email


# Currently available features
- [x] Parse website and save data as raw-data report file (currently hardcoded for Ogre city adjust to your needs)
- [x] Generate basic user freandly report in formatat of one line for each advertisement
- [x] Send email to gmail with report that was read from text file 
- [x] Email report includes filter option by rooms count

# TODO Backlog
- [x] Add date field extraction feature (not in email report)
- [x] Add view count field extraction feature (not in email report)
- [ ] Add feature ability to save raw data as Pandas dataframe in CSV format
- [ ] Add master page subpage detection and iteration feature
- [ ] Add Data sience methods and prittify reports
- [ ] Add analitics module find min/max/average prices for your filter rules 



  
