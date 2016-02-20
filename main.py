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

import logging
import cloudstorage as gcs
import urlparse

siteName = "http://svgur.com"

svgcounter = increment.Increment("svg-id", 10)

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
    
class MainHandler(webapp2.RequestHandler):
  def get(self):
    upload_url = blobstore.create_upload_url('/upload')
    template = JINJA_ENVIRONMENT.get_template('homepage.html')
    qry = SvgPage.query().order(-SvgPage.published)
    recentpix=qry.fetch(50)
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

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
  def get(self, filename):
    bits= filename.split('.')
    key = bits[0]
    extension = '.svg'
    if len(bits)>1:
        extension = bits[1] #awaiting conditional code for png/jpg
    resource = int(newbase60.sxgtonum(urllib.unquote(key)))
    qry = SvgPage.query(SvgPage.svgid == resource)
    pages = qry.fetch(1)
    blob_info = blobstore.BlobInfo.get(pages[0].svgBlob)
    self.send_blob(blob_info)
  def head(self, filename):
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 
    
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
    template = JINJA_ENVIRONMENT.get_template('svgpage.html')
    svgVals = { 'name':pages[0].name,
                'summary':pages[0].summary,
                'published':pages[0].published,
                'url':'/i/'+ svgStr+'.svg',
                'rawurl':'/raw/'+ str(pages[0].svgBlob),
                'image_link':siteName+'/s/'+svgStr,
                'iframe_link':siteName+'/f/'+ svgStr,
                'direct_link':siteName+'/i/'+ svgStr+'.svg',
                'png_link':siteName+'/p/'+ svgStr+'.png'
                }
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 
    self.response.write(template.render(svgVals))    
  def head(self, filename):
    self.response.headers["Link"] = '<https://webmention.herokuapp.com/api/webmention>; rel="webmention"' 
    

app = webapp2.WSGIApplication([('/', MainHandler),
                               ('/s/([^/]+)?', SvgHandler),
                               ('/upload', UploadHandler),
                               ('/i/([^/]+)?', ServeHandler),
                               ('/f/([^/]+)?', FrameHandler),
                               ('/p/([^/]+)?', PngHandler),
                               ('/makepingfromsvg/([^/]+)?', PngFromSvgHandler),
                               ('/raw/([^/]+)?', RawServeHandler)],
                              debug=True)