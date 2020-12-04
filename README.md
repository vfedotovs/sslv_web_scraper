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
- [x] Add date field extraction feature 
    - [ ] Bug: date values are incorrect compared to website
    - [ ] Bug: date field is not included in email report
    - [ ] Add feature count how many days ago ad was published
- [x] Add view count field extraction feature
  - [ ] Bug: view count field value is allways 1 wich is not correct
  - [ ] Bug: view count field value is not included in email report
  - [ ] Add feature find bigges view count ads (Will help answer what is hot/trending?)
- [x] Add feature ability to save raw data as Pandas dataframe in CSV format
- [x] Add pandas data frame clean-up 
- [x] Add basic analytics functionality plot graphs and filter and sort data frame
  - [ ] Add analytics plot export/save to pdf/png/html for further usage by mauler module  
- [x] Add basic calculations:
  - [x] Count filtered apartents by room count
  - [x] Find average apartment price for section filtered apartents by room count
  - [ ] Find min/max prices
- [ ] Add master page subpage URL extraction and iteration feature




  
