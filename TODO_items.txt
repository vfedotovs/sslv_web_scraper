### Release 2.0.0 status  aka (Milestone 2)###
1. [x] web_sracper.py module - ready will use old one
2. [x] df_cleaner.py is new module ready 
       -[x] cleans up dataframe and creates clean-data.csv

3. [x] analitics.py 77 lines - basic functionality done 
    - [x] uses file from module 2
    - [x] functionality calculate and  save bare minimum stats to txt files for import to pdf creator
    - [ ] implement more advanced stats mentioned at the end of the file

4 [ ] report_creator.py 
    - [x] uses csv file from module 2
    - [x] png chart generation works
    - [ ] buld multisection (include title, statstxt, advert data,  graphs in png) pfd file
        - [x] build pfd file bare minimum works
        - [x] import png FILE TO PDF  basic works
        - [x] import text stats from module 3 to pdf - not available
        - [ ] import adverts by single or double room category from df tp pdf - not vailable

5. [x] sendbird_miler.py
    - [x] test send email with no attachment works
    - [x] test send email with pdf atachment works
    - [x] code not added to repo and secrets
    - [x] (API key,  source dest emails) handling not added to repo 

6. [ ] code quality improvemet
    -[ ] ensure that all code is linte dby pylint and formated by yapf
    -[ ] add src of sslv_sraper folder with app.py and other files
    -[ ] add data folder - that stores output df scv, png, pdf files that are used by other modules
    -[ ] add docs - documentaion .md files
    -[ ] add tests folder - get some practice in testing
    -[ ] add docker file is L1 devops level cam manualy build image and deploy docker image on aws or localy in VM
    -[ ] add jenkins file is L2 CICD - commit triggers run tests, rebuild of docker image ane deploy new image in AWS 



### Release 3.0.0 status aka (Milestone 3) ###
flask as webserver 
AWS VM
database to store history of ads and registered users 
add multople cities repors
add username reports
Authentication for users
subscription to receive email specific city for authenticated user 


### To create venv ###
python3 -m venv env

### activate venv ###
source env/bin/activate

### some stats how many lines of code in each project python file ###
    data_formater.py 132 
      web_scraper.py 141 
      pdf_creator.py 157 
              app.py 30  
          gmailer.py 35  
  sendgrid_mailer.py 37  
       df_cleaner.py 78  
        analytics.py 93  

### command to get line stats ###
for f in $(ls -1 | grep .py$); do file=$f ; lc=$(cat $f| wc -l); printf "%20s %-3d \n" "$f" " $lc" ;done | sort -k 2 >> TODO_items.txt 


### This is git merge dry run -- yet to be tested ###
git merge --no-commit --no-ff main
