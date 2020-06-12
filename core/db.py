import pymongo
import time
import functools
import copy
from bson.objectid import ObjectId

# DB Document Class
class _document():
    _id = str()
    classID = str()
    acl = dict()
    lastUpdateTime = int()

    def __init__(self):
        pass

    # Wrapped mongo call that catches and retrys on error
    def mongoConnectionWrapper(func):
        @functools.wraps(func)
        def wrapper(inst, *args, **kwargs):
            while True:
                try:
                    return func(inst, *args, **kwargs)
                except (pymongo.errors.AutoReconnect, pymongo.errors.ServerSelectionTimeoutError) as e:
                    logging.debug("PyMongo auto-reconnecting... {0}. Waiting 1 second.".format(e),-10)
                    time.sleep(1)
        return wrapper

    # Create new object
    @mongoConnectionWrapper
    def new(self):
        # Confirming that the new class has been regisrted as a model
        result = model._model().query(query={"className" : self.__class__.__name__})["results"]
        if len(result) == 1:
            result = result[0]
            self.classID = result["_id"]
            result = self._dbCollection.insert_one(self.parse())
            self._id = result.inserted_id
            return result
        else:
            logging.debug("Cannot create new document className='{0}' not found".format(self.__class__.__name__),3)
            return False

    # Converts jsonList into class - Seperate function to getAsClass so it can be overridden to support plugin loading for child classes
    def loadAsClass(self,jsonList,sessionData=None):
        result = []
        # Loading json data into class
        for jsonItem in jsonList:
            _class = copy.copy(self)
            result.append(helpers.jsonToClass(_class,jsonItem))
        return result

    # Get objects and return list as loaded class
    @mongoConnectionWrapper
    def getAsClass(self,sessionData=None,fields=[],query=None,id=None,limit=None,sort=None):
        jsonResults = self.query(sessionData,fields,query,id,limit,sort)["results"]
        return self.loadAsClass(jsonResults,sessionData=sessionData)
    
    # Get a object by ID
    def get(self,id):
        result = self.load(id)
        if not result:
            return None
        return self

    # Refresh data from database
    def refresh(self):
        queryResults = findDocumentByID(self._dbCollection,self._id)
        if queryResults:
            helpers.jsonToClass(self,queryResults)

    # Updated DB with latest values
    @mongoConnectionWrapper
    def update(self,fields):
        # Appendingh last update time to every update
        fields.append("lastUpdateTime")
        self.lastUpdateTime = time.time()

        update = { "$set" : {} }
        for field in fields:
            update["$set"][field] = getattr(self,field)
        result = updateDocumentByID(self._dbCollection,self._id,update)
        return result
        
    # Parse class into json dict
    def parse(self,hidden=False):
        result = helpers.classToJson(self,hidden)
        return result

    # Parse DB dict into class
    @mongoConnectionWrapper
    def load(self,id):
        queryResults = findDocumentByID(self._dbCollection,id)
        if queryResults:
            helpers.jsonToClass(self,queryResults)
            return self
        else:
            return None

    # Delete loaded class from DB
    @mongoConnectionWrapper
    def delete(self):
        query = { "_id" : ObjectId(self._id) }
        result = self._dbCollection.delete_one(query)
        if result.deleted_count == 1:
            return { "result" : True, "count" : result.deleted_count }
        return { "result" : False, "count" : 0 }        

    @mongoConnectionWrapper
    def insert_one(self,data):
        self._dbCollection.insert_one(data)

    def getAttribute(self,attr):
        return getattr(self,var)

    def setAttribute(self,attr,value):
        setattr(self,attr,value)
        return True

    # API Calls - NONE LOADED CLASS OBJECTS <<<<<<<<<<<<<<<<<<<<<< Will need to support decorators to enable plugin support?
    @mongoConnectionWrapper
    def query(self,sessionData=None,fields=[],query=None,id=None,limit=None,sort=None):
        result = { "results" : [] }
        if fields is None:
            fields = []
        if id and not query:
            try:
                query = { "_id" : ObjectId(id) }
            except Exception as e:
                logging.debug("Error {0}".format(e))
                return result
        if not query:
            query = {}
        # Builds list of permitted ACL
        accessIDs = []
        adminBypass = False
        if sessionData and authSettings["enabled"]:
            if "admin" in sessionData:
                if sessionData["admin"]:
                    adminBypass = True
            if not adminBypass:
                accessIDs = sessionData["accessIDs"]
                # Adds ACL check to provided query to ensure requester is authorised and had read acess
                aclQuery = { "$or" : [ { "acl.ids.accessID" : { "$in" : accessIDs }, "acl.ids.read" : True }, { "acl" : { "$exists" : False } }, { "acl" : {} } ] }
                if "$and" in query:
                    query["$and"].append(aclQuery)
                elif "$or" in query:
                    query["$and"] = [ aclQuery ]
                else: 
                    query["$or"] = [ aclQuery ]
        # Base query
        docs = self._dbCollection.find(query)
        # Apply sorting
        if sort:
            docs.sort(sort)
        # Apply limits
        if limit:
            docs.limit(limit)                        
        # Sort returned data into json API response
        for doc in docs:
            resultItem = {}
            if len(fields) > 0:
                for field in fields:
                    if field in doc:
                        fieldAccessPermitted = True
                        # Checking if sessionData is permitted field level access
                        if "acl" in doc and not adminBypass and sessionData and authSettings["enabled"]:
                            fieldAccessPermitted = fieldACLAccess(accessIDs,doc["acl"],field)
                        # Allow field data to be returned if access is permitted
                        if fieldAccessPermitted:
                            value = helpers.handelTypes(doc[field])
                            if type(value) is dict:
                                value = helpers.unicodeUnescapeDict(value)
                            resultItem[helpers.unicodeUnescape(field)] = value
            else:
                for field in list(doc):
                    fieldAccessPermitted = True
                    # Checking if sessionData is permitted field level access
                    if "acl" in doc and not adminBypass and sessionData and authSettings["enabled"]:
                        fieldAccessPermitted = fieldACLAccess(accessIDs,doc["acl"],field)
                    # Allow field data to be returned if access is permitted
                    if fieldAccessPermitted:
                        value = helpers.handelTypes(doc[field])
                        if type(value) is dict:
                            value = helpers.unicodeUnescapeDict(value)
                        resultItem[helpers.unicodeUnescape(field)] = value
            result["results"].append(resultItem)
        docs.close()
        return result

    @mongoConnectionWrapper
    def count(self,sessionData=None,query=None,id=None):
        result = { "results" : [] }
        if id and not query:
            try:
                query = { "_id" : ObjectId(id) }
            except Exception as e:
                logging.debug("Error {0}".format(e))
                return result
        if not query:
            query = {}
        # Builds list of permitted ACL
        accessIDs = []
        adminBypass = False
        if sessionData and authSettings["enabled"]:
            if "admin" in sessionData:
                if sessionData["admin"]:
                    adminBypass = True
            if not adminBypass:
                accessIDs = sessionData["accessIDs"]
                # Adds ACL check to provided query to ensure requester is authorised and had read acess
                aclQuery = { "$or" : [ { "acl.ids.accessID" : { "$in" : accessIDs }, "acl.ids.read" : True }, { "acl" : { "$exists" : False } }, { "acl" : {} } ] }
                if "$and" in query:
                    query["$and"].append(aclQuery)
                elif "$or" in query:
                    query["$and"] = [ aclQuery ]
                else: 
                    query["$or"] = [ aclQuery ]
        # Base query
        count = self._dbCollection.count(query)    
        #return count           
        result["results"].append({"count" : count})
        return result

    @mongoConnectionWrapper
    def api_getByModelName(self,modelName):
        classID = model.getClassID(modelName)
        if classID:
            return self.query(query={ "classID" : classID })
        return { "results" : [] }

    @mongoConnectionWrapper
    def api_delete(self,query=None,id=None):
        if id and not query:
            try:
                query = { "_id" : ObjectId(id) }
                result = self._dbCollection.delete_one(query)
                if result.deleted_count == 1:
                    return { "result" : True, "count" : result.deleted_count }
            except Exception as e:
                logging.debug("Error {0}".format(e))
        elif query and not id:
            try:
                result = self._dbCollection.delete_many(query)
                if result.deleted_count > 0:
                    return { "result" : True, "count" : result.deleted_count }
            except Exception as e:
                logging.debug("Error {0}".format(e))
        return { "result" : False, "count" : 0 }

    @mongoConnectionWrapper
    def api_update(self,query={},update={}):
        if "_id" in query:
            try:
                query["_id"] = ObjectId(query["_id"])
            except Exception as e:
                logging.debug("Error {0}".format(e))
        result = self._dbCollection.update_many(query,update)
        return { "result" : True, "count" :  result.modified_count }

    @mongoConnectionWrapper
    def api_add(self,postData):
        newObj = {}
        schema = self.api_getSchema()
        for key, value in schema.items():
            if key in postData:
                if type(postData[key]).__name__ == value:
                    newObj[key] == postData[key]
        if newObj != {}:
            result = _dbCollection.insert_one(newObj)
            return { "result" : True, "id" : result.inserted_id }

        return { "result" : False }

    @mongoConnectionWrapper
    def api_getSchema(self):
        result = {}
        for key, value in self.parse(True).items():
            result[key] = type(value).__name__
        return result


from core import settings, logging, helpers, model

mongodbSettings = settings.config["mongodb"]
authSettings = settings.config["auth"]

dbClient = pymongo.MongoClient("mongodb://{0}:{1}/".format(mongodbSettings["host"],mongodbSettings["port"]))

db = dbClient[mongodbSettings["db"]]

# DB Helper Functions
def list_collection_names():
    return db.list_collection_names()

# Checks if access to a field is permitted by the object ACL
def fieldACLAccess(accessIDs,acl,field,accessType="read"):
    if not authSettings["enabled"]:
        return True
    if "fields" in acl:
        fieldAcls = [ x for x in acl["fields"] if field == x["field"] ]
        if len(fieldAcls) == 0:
            return True
        # Checking if the sessionData permits access to the given ACL
        for fieldAcl in fieldAcls:
            for accessID in fieldAcl["ids"]:
                if accessID["accessID"] in accessIDs and accessID[accessType]:
                    return True
    else:
        return True
    return False

# Checks if access to the object is permitted by the object ACL
def ACLAccess(sessionData,acl,accessType="read"):
    if not authSettings["enabled"]:
        return [ True, [], False ]
    accessIDs = []
    access = False
    adminBypass = False
    if sessionData:
        adminBypass = False
        if "admin" in sessionData:
            if sessionData["admin"]:
                adminBypass = True
                access = True
        if not adminBypass:
            accessIDs = sessionData["accessIDs"]
            if acl:
                for aclItem in acl["ids"]:
                    for accessID in accessIDs:
                        if aclItem["accessID"] == accessID:
                            access = aclItem[accessType]
            else:
                access = True
    return [ access, accessIDs, adminBypass ]


# Update DB item within giben collection by ID
def updateDocumentByID(dbCollection,id,update):
    query = { "_id" : ObjectId(id) }
    queryResults = dbCollection.update_one(query, update)
    return queryResults

# Get DB item within given collection by ID
def findDocumentByID(dbCollection,id):
    query = { "_id" : ObjectId(id) }
    queryResults = dbCollection.find_one(query)
    return queryResults

# Delete database
def delete():
    dbClient.drop_database(mongodbSettings["db"]) 

logging.debug("db.py loaded")