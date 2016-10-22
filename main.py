#!/usr/bin/env python
#

from __future__ import with_statement
import os
import urllib
import jinja2
import webapp2
import increment
import newbase60
import base64
from google.appengine.api import files
from google.appengine.api import app_identity
from google.appengine.api import urlfetch
from google.appengine.api import taskqueue
import hashlib
import json

import logging
import cloudstorage as gcs
import urlparse
import openanything
import datetime
from google.appengine.api import urlfetch


if os.getenv('SERVER_SOFTWARE', '').startswith('Google App Engine/'):
    siteName = "http://svgshare.com"
else:
    siteName = "http://localhost:10080"
svgcounter = increment.Increment("svg-id", 10)
oldSiteName = "http://svgur.com"
JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext import ndb
from google.appengine.api import images


class SvgPage(ndb.Model):
    """Models an individual svg page."""
    svgid = ndb.IntegerProperty(indexed=True)
    svgBlob = ndb.BlobKeyProperty(indexed=True)
    pngBlob = ndb.BlobKeyProperty(indexed=True)
    pngFile = ndb.StringProperty(indexed=False)
    published = ndb.DateTimeProperty(auto_now_add=True)
    name = ndb.StringProperty(indexed=True)
    summary = ndb.StringProperty(indexed=False)
    svghash = ndb.StringProperty(indexed=True) # sha1 hash of svg
    def getHash(self, hashtype='sha1'):
        """Make a SubResource Integrity compatible hash, but using sha1 by default as they exist."""
        if not self.svghash:
            blob_reader = blobstore.BlobReader(self.svgBlob)
            digest = hashlib.sha1(blob_reader.read()).digest()
            self.svghash = "sha1-%s" % (base64.b64encode(digest))
            self.put() # write back hash
        return self.svghash
    def getLink(self, kind="image",absolute=True,site=siteName):
        svgStr = newbase60.numtosxg(self.svgid)
        if kind=='hash':
            link ="/getbyhash/%s" % (self.getHash())
        else:
            pattern = {'iframe':'/f/%s', 'direct':'/i/%s.svg', 'png':'/p/%s.png'}.get(kind,'/s/%s')
            link = pattern % (svgStr)
        if absolute:
            link = site+link
        return link
    
class MainHandler(webapp2.RequestHandler):
  def get(self):
    upload_url = blobstore.create_upload_url('/upload')
    template = JINJA_ENVIRONMENT.get_template('homepage.html')
    qry = SvgPage.query().order(-SvgPage.published)
    recentpix=qry.fetch(60)
    pix = [ {"name":"%s" % page.name, "svgid":newbase60.numtosxg(page.svgid),"published":page.published} for page in recentpix]
    self.response.write(template.render({'upload_url':upload_url, 'pix':pix}))

class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
  def post(self):
    upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
    blob_info = upload_files[0]
    page = SvgPage()
    page.name = self.request.get('name',"")
    page.summary = self.request.get('summary',"")
    page.svgBlob=blob_info.key()
    page.svgid = svgcounter.one()
    hash = page.getHash()
    logging.info(" id %s hash '%s'" % (page.svgid,hash))
    page.put()
    self.redirect('/s/%s' % newbase60.numtosxg(page.svgid))
    taskqueue.add(url='/makepingfromsvg/%s' % newbase60.numtosxg(page.svgid))
    
class PngFromSvgHandler(webapp2.RequestHandler):
  def post(self, filename):
    status="pending"
    bits= filename.split('.')
    key = bits[0]
    extension = '.png'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    width = str(self.request.get('width', "0"))
    force = self.request.get('force')
    pages = qry.fetch(1)
    page=None
    if len(pages)>0:
        page = pages[0]
    if not page:
        status="no such svg"
    elif not force and page.pngFile:
        status="file exists"
    else:
        urlbits= list(urlparse.urlsplit(self.request.uri))
        urlbits[2] = '/f/'+key
        urlbits[3] = ''
        svgurl= urlparse.urlunsplit(urlbits)
        url = "https://savageping.herokuapp.com/u?" + urllib.urlencode({"url":svgurl,"width":1024})
        urlfetch.set_default_fetch_deadline(180)
        result = urlfetch.fetch(url)
        rawpng=None
        if result.status_code == 200:
          rawpng= result.content
        else:
            status="error from service: %s" %(result.status_code)
        if (rawpng):
            logging.info(" png %s" % rawpng[0:256])
            bucket_name = os.environ.get('BUCKET_NAME',
                                         app_identity.get_default_gcs_bucket_name())
            filename = '/' + bucket_name + '/p/%s.png' % newbase60.numtosxg(page.svgid)
            gcs_file = gcs.open(filename, 'w', content_type='image/png')
            gcs_file.write(rawpng)
            gcs_file.close()
            # Get the file's blob key
            #page.pngBlob = blobstore.create_gs_key("/gs"+ filename)
            page.pngFile =  blobstore.create_gs_key("/gs"+ filename)
            status="file created"
            page.put()
    logging.info("PngFromSvgHandler "+ key +" status: " + status)
    self.response.write("svg to png "+ key +" status: " + status) 

    
class PngHandler(webapp2.RequestHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    extension = '.png'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    width = str(self.request.get('width', "0"))
    pages = qry.fetch(1)
    if pages[0].pngBlob:
        self.redirect(images.get_serving_url(pages[0].pngBlob)+"=s"+width)
    elif pages[0].pngFile:
        try:
            self.redirect(images.get_serving_url(pages[0].pngFile)+"=s"+width)
        except:
            pages[0].pngFile = None
            pages[0].put()
            taskqueue.add(url='/makepingfromsvg/%s' % key)
            self.redirect('/s/'+filename)
    else:
        taskqueue.add(url='/makepingfromsvg/%s' % key)
        self.redirect('/s/'+filename)
  def head(self, filename):
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, filename, isHead=False):
    bits= filename.split('.')
    key = bits[0]
    extension = '.svg'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    etag = pages[0].getHash().encode('utf8')
    self.response.headers["Etag"] = '%s' % etag
    logging.info("ServeHandler file: '%s' ETag '%s'" %(filename, self.response.headers["Etag"]))
    self.response.headers["Cache-Control"]="public, max-age=315360000"
    self.response.headers["Content-Type"]= 'image/svg+xml'
    if self.request.headers.get('If-None-Match','') == etag:
        self.response.status_int = 304
        self.response.status_message = "Not Modified"
        self.response.status = "304 Not Modified"
        self.response.out.write('')
    elif not isHead:
        blob_info = blobstore.BlobInfo.get(pages[0].svgBlob)
        self.send_blob(blob_info)
    else:
        self.response.out.write('')
  def head(self, filename):
    logging.info("ServeHandler head file: '%s' " %(filename))
    self.get(filename,isHead=True)
    
class FrameHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    extension = '.svg'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    svgStr = newbase60.numtosxg(resource)
    blob_info = blobstore.BlobInfo.get(pages[0].svgBlob)
    template = JINJA_ENVIRONMENT.get_template('iframe.html')
    reader = blobstore.BlobReader(blob_info)
    rawsvg = reader.read().decode('utf-8')
    svgVals = { 'name':pages[0].name,
                'svg': rawsvg,
                'image_link':siteName+'/s/'+svgStr,
                'url':'/i/'+ svgStr+'.svg',
                }
    self.response.write(template.render(svgVals))    


class RawServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, resource):
    resource = str(urllib.unquote(resource))
    blob_info = blobstore.BlobInfo.get(resource)
    self.send_blob(blob_info)

class SvgHandler(webapp2.RequestHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    svgStr = newbase60.numtosxg(resource)
    if pages:
        etag = pages[0].getHash().encode('utf8')
        self.response.headers["Etag"] = '%s' % etag
        template = JINJA_ENVIRONMENT.get_template('svgpage.html')
        svgVals = { 'name':pages[0].name,
                    'summary':pages[0].summary,
                    'published':pages[0].published,
                    'url':'/i/'+ svgStr+'.svg',
                    'rawurl':'/raw/'+ str(pages[0].svgBlob),
                    }
        for kind in ('image','iframe','direct','png','hash'):
            svgVals[kind+"_link"] = pages[0].getLink(kind)
            svgVals["old_link"] = pages[0].getLink('image',site=oldSiteName)
        self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"'
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"No such image as %s" % filename }
        self.response.set_status(404)
    self.response.write(template.render(svgVals))
    
class IdToHashHandler(webapp2.RequestHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    logging.info("UrlToHashHandler file: '%s' key:'%s' resource:'%s'" %(filename,key,resource))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    if pages:
        output = [{'url':pages[0].getLink('direct'),'hash':pages[0].getHash(), 'date':pages[0].published.isoformat()}]
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(output))
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"No such image as %s" % filename }
        self.response.set_status(404)
        self.response.write(template.render(svgVals))

class UrlToHashHandler(webapp2.RequestHandler):
  def get(self):
    url=self.request.get('url',"")
    if url:
        if "://" not in url:
            url = "http://"+url
    filename = urlparse.urlsplit(url).path.split('/')[-1]
    bits= filename.split('.')
    key = bits[0]
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    logging.info("UrlToHashHandler url: '%s', file: '%s' key:'%s' resource:'%s'" %(url,filename,key,resource))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    if pages:
        output = [{'url':pages[0].getLink('direct'),'hash':pages[0].getHash(), 'date':pages[0].published.isoformat()}]
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(output))
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"No url here like '%s'" % url }
        self.response.set_status(404)
        self.response.write(template.render(svgVals))

def Base32toBase64(s):
    return base64.b64encode(base64.b32decode(s))
    

class ArchiveUrlToHashHandler(webapp2.RequestHandler):
  def get(self):
    url=self.request.get('url',"")
    if url:
        if "://" not in url:
            url = "http://"+url
    filename = urlparse.urlsplit(url).path.split('/')[-1]
    bits= filename.split('.')
    key = bits[0]
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    logging.info("ArchiveUrlToHashHandler url: '%s' " %(url))
    uthparams = openanything.fetch('http://web.archive.org/cdx/search/cdx?url=%s' %(urllib.quote(url)))
    logging.info("ArchiveUrlToHashHandler urltohash: '%s' status: '%s' " %(uthparams.get('data','uh oh'),uthparams.get('status','?')))
    #format is com,svgur)/i/au.svg 20160829212327 http://svgur.com/i/AU.svg image/svg+xml 200 LY7RXMB7SLQLKEB63LGFNYY7F3SYRCNQ 3079
    output=[]
    for line in uthparams.get('data','').splitlines():
        qpath,fetchdate,foundurl,mimetype,result,base32hash,length = line.split(' ')
        if result == '200':
            output.append({'url':foundurl,'hash':'sha1-%s' % (Base32toBase64(base32hash)), 'date':datetime.datetime.strptime(fetchdate,'%Y%m%d%H%M%S').isoformat()})
    if output:
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(output))
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"No url here like '%s'" % url }
        self.response.set_status(404)
        self.response.write(template.render(svgVals))



class HashToUrlHandler(webapp2.RequestHandler):
  def get(self, hash):
    logging.info("HashToUrlHandler hash: '%s'" %(hash))
    qry = SvgPage.query(SvgPage.svghash == hash)
    pages = qry.fetch(10)
    output= []
    if pages:
        output = [{'url':page.getLink('direct'),'hash':page.getHash(), 'date':page.published.isoformat()} for page in pages]
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(output))
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"No such image hash as %s" % hash }
        self.response.set_status(404)
        self.response.write(template.render(svgVals))

class GetbyHashHandler(webapp2.RequestHandler):
  def get(self, hash):
    qry = SvgPage.query(SvgPage.svghash == hash)
    pages = qry.fetch(1)
    if pages:
        self.redirect(pages[0].getLink('direct'))
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"No such image hash as %s" % hash }
        self.response.set_status(404)
        self.response.write(template.render(svgVals))

class ProxyHandler(webapp2.RequestHandler):
  def get(self):
    url=self.request.get('url',"")
    if url:
        if "://" not in url:
            url = "http://"+url
    logging.info("ProxyHandler url: '%s' " %(url))
    uthparams = openanything.fetch(siteName+'/urltohash?url=%s' %(urllib.quote(url)))
    logging.info("ProxyHandler urltohash: '%s' status: '%s' " %(uthparams.get('data','uh oh'),uthparams.get('status','?')))
    hashinfo = json.loads(uthparams.get('data','[]'))
    finalurl=''
    if hashinfo:
        thehash = hashinfo[0].get('hash','')
        if thehash:
            h2uparams = openanything.fetch(siteName+'/hashtourl/%s' %(thehash))
            logging.info("ProxyHandler hashtourl: '%s' status: '%s' " %(h2uparams.get('data','uh oh'),h2uparams.get('status','?')))
            urlinfo = json.loads(h2uparams.get('data','[]'))
            if urlinfo:
                finalurl = urlinfo[0].get('url','').encode('utf8')
    if finalurl:
        self.redirect(finalurl)
    else:
        template = JINJA_ENVIRONMENT.get_template('errorpage.html')
        svgVals = { 'error':"Proxy can't find a hash for %s" % url }
        self.response.set_status(404)
        self.response.write(template.render(svgVals))

class DwebHandler(webapp2.RequestHandler):
  def get(self):
    url=self.request.get('url',"")
    if not url:
        url = "http://svgur.com/i/AU.svg"
    if url:
        if "://" not in url:
            url = "http://"+url
    thehash=''
    uthparams = openanything.fetch(siteName+'/urltohash?url=%s' %(urllib.quote(url)))
    if uthparams.get('status') == 200:
        hashinfo = json.loads(uthparams.get('data','[]'))
        if hashinfo:
            thehash = hashinfo[0].get('hash','')
    template = JINJA_ENVIRONMENT.get_template('dweb.html')
    vals = { 'url':url, 'proxyurl':'/proxy?url=%s' %(urllib.quote(url)),
            'urltohash':'/urltohash?url=%s' %(urllib.quote(url)), 
            'iaurltohashraw':'http://web.archive.org/cdx/search/cdx?url=%s' %(urllib.quote(url)), 
            'iaurltohash':'/iaurltohash?url=%s' %(urllib.quote(url)), 
            'haurltohash':'https://hash-archive.org/history/%s' %(url), 
            'hashtourl':'/hashtourl/'+thehash,
            'hasharchive':'https://hash-archive.org/sources/'+thehash,
            }
    self.response.write(template.render(vals))

  def head(self, filename):
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 
    

app = webapp2.WSGIApplication([('/', MainHandler),
                               ('/s/([^/]+)?', SvgHandler),
                               ('/upload', UploadHandler),
                               ('/i/([^/]+)?', ServeHandler),
                               ('/f/([^/]+)?', FrameHandler),
                               ('/p/([^/]+)?', PngHandler),
                               ('/makepingfromsvg/([^/]+)?', PngFromSvgHandler),
                               ('/raw/([^/]+)?', RawServeHandler),
                               ('/idtohash/([^/]+)?', IdToHashHandler),
                               ('/urltohash', UrlToHashHandler),
                               ('/iaurltohash', ArchiveUrlToHashHandler),
                               ('/hashtourl/(.+)', HashToUrlHandler),
                               ('/getbyhash/(.+)?', GetbyHashHandler),
                               ('/proxy', ProxyHandler),
                               ('/dweb', DwebHandler),
                               ],
                              debug=True)