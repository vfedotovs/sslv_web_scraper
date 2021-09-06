from configparser import ConfigParser
import os


host = os.environ['DB_HOST']
databse= os.environ['DB_NAME']
db_user = os.environ['DB_USER']
password= os.environ['DB_PASSWORD']



def config():
    """ dirty workaround testing env pass to docker"""
    db = {}
    db['host'] = host
    db['database'] = database
    db['user'] = db_user
    db['password'] = password
    return db


#def config(filename='database.ini', section='postgresql'):
#    """ Reading database.ini file data and return it as db dictionary """
#    parser = ConfigParser()        # create a parser
#    parser.read(filename)          # read config file
#    db = {}                        # get section, default to postgresql
#    if parser.has_section(section):
#        params = parser.items(section)
#        for param in params:
#            db[param[0]] = param[1]
#    else:
#        raise Exception('Section {0} not found in the {1} file'.format(section, filename))
#    return db
