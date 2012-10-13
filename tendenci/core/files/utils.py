import Image
from os.path import exists
from cStringIO import StringIO
import os
import httplib
import urllib
import urllib2
from urlparse import urlparse
from django.core.files.base import ContentFile
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.shortcuts import Http404
from django.core.cache import cache as django_cache
from tendenci.core.base.utils import image_rescale
from tendenci.libs.boto_s3.utils import read_media_file_from_s3

from tendenci.core.files.models import File as TFile
from tendenci.core.files.models import file_directory


def get_image(file, size, pre_key, crop=False, quality=90, cache=False, unique_key=None, constrain=False):
    """
    Gets resized-image-object from cache or rebuilds
    the resized-image-object using the original image-file.
    *pre_key is either:
        from tendenci.addons.photos.cache import PHOTO_PRE_KEY
        from tendenci.core.files.cache import FILE_IMAGE_PRE_KEY
    """

    size = validate_image_size(size)  # make sure it's not too big
    binary = None

    if cache:
        key = generate_image_cache_key(file, size, pre_key, crop, unique_key, quality, constrain)
        binary = django_cache.get(key)  # check if key exists

    if not binary:
        kwargs = {
            'crop': crop,
            'cache': cache,
            'quality': quality,
            'unique_key': unique_key,
            'constrain': constrain,
        }
        binary = build_image(file, size, pre_key, **kwargs)

    try:
        return Image.open(StringIO(binary))
    except:
        return ''


def build_image(file, size, pre_key, crop=False, quality=90, cache=False, unique_key=None, constrain=False):
    """
    Builds a resized image based off of the original image.
    """

    try:
        quality = int(quality)
    except:
        quality = 90

    if settings.USE_S3_STORAGE:
        content = read_media_file_from_s3(file)
        image = Image.open(StringIO(content))
    else:
        if hasattr(file, 'path') and exists(file.path):
            image = Image.open(file.path)  # get image
        else:
            raise Http404

    # handle infamous error
    # IOError: cannot write mode P as JPEG
    if image.mode != "RGB":
        image = image.convert("RGB")

    if crop:
        image = image_rescale(image, size)  # thumbnail image
    else:
        image = image.resize(size, Image.ANTIALIAS)  # resize image

    # mission: get binary
    output = StringIO()
    image.save(output, "JPEG", quality=quality)
    binary = output.getvalue()  # mission accomplished
    output.close()

    if cache:
        key = generate_image_cache_key(file, size, pre_key, crop, unique_key, quality, constrain)
        django_cache.add(key, binary, 60 * 60 * 24 * 30)  # cache for 30 days #issue/134

    return binary


def validate_image_size(size):
    """
    We cap our image sizes to avoid processor overload
    This method checks the size passed and returns
    a valid image size.
    """
    max_size = (2048, 2048)
    new_size = []

    # limit width and height exclusively
    for item in zip(size, max_size):
        if item[0] > item[1]:
            new_size.append(item[1])
        else:
            new_size.append(item[0])

    return new_size


def aspect_ratio(image_size, new_size, constrain=False):
    """
    The image_size is a sequence of integers (200, 300)
    The new_size is a sequence of integers (200, 300)
    The constrain limits to within the new_size parameters.
    """

    w, h = new_size

    if not constrain and (w and h):
        return w, h

    if bool(w) != bool(h):
        if w:
            return constrain_size(image_size, [w, 0])
        return constrain_size(image_size, [0, h])

    if not constrain:
        if bool(w) != bool(h):
            return constrain_size(image_size, [w, 0])

    w1, h1 = constrain_size(image_size, [w, 0])
    w2, h2 = constrain_size(image_size, [0, h])

    if h1 <= h:
        return w1, h1

    return w2, h2


def constrain_size(image_size, new_size):
    """
    Take the biggest integer in the 2-item sequence
    and constrain on that integer.
    """

    w, h = new_size
    max_size = max(new_size)

    ow, oh = image_size  # original width and height
    if oh and ow:
        ow = float(ow)

        if w == max_size or h == '0':
            h = (oh / ow) * w
        else:  # height is max size
            w = h / (oh / ow)

    return int(w), int(h)


def generate_image_cache_key(file, size, pre_key, crop, unique_key, quality, constrain=False):
    """
    Generates image cache key. You can use this for adding,
    retrieving or removing a cache record.
    """
    str_size = ''
    if size:
        if 'x' in size:
            str_size = str(size)
        else:
            str_size = 'x'.join([str(i) for i in size])
    str_quality = str(quality)

    if crop:
        str_crop = "cropped"
    else:
        str_crop = ""

    if constrain:
        str_constrain = "constrain"
    else:
        str_constrain = ""

    # e.g. file_image.1294851570.200x300 file_image.<file-system-modified-time>.<width>x<height>
    if unique_key:
        key = '.'.join((settings.CACHE_PRE_KEY, pre_key, unique_key, str_size, str_crop, str_quality, str_constrain))
    else:
        key = '.'.join((settings.CACHE_PRE_KEY, pre_key, str(file.size), file.name, str_size, str_crop, str_quality, str_constrain))
    # Remove spaces so key is valid for memcached
    key = key.replace(" ", "_")

    return key


class AppRetrieveFiles(object):
    """
    Retrieve files (images) from src url.
    """
    def __init__(self, **kwargs):
        self.site_url = kwargs.get('site_url')
        self.site_domain = urllib2.Request(self.site_url).get_host()
        self.src_url = kwargs.get('src_url')
        self.src_domain = urllib2.Request(self.src_url).get_host()
        self.p = kwargs.get('p')
        self.replace_dict = {}
        self.total_count = 0

    def process_app(self, app_name, **kwargs):
        if app_name == 'articles':
            from tendenci.addons.articles.models import Article

            articles = Article.objects.all()
            for article in articles:
                print 'Processing article - ', article.id,  article
                kwargs['instance'] = article
                updated, article.body = self.process_content(
                                        article.body, **kwargs)

                if updated:
                    article.save()
        elif app_name == 'news':
            from tendenci.addons.news.models import News
            news = News.objects.all()
            for n in news:
                print 'Processing news -', n.id, n
                kwargs['instance'] = n
                updated, n.body = self.process_content(
                                        n.body, **kwargs)
                if updated:
                    n.save()
        elif app_name == 'pages':
            from tendenci.apps.pages.models import Page
            pages = Page.objects.all()
            for page in pages:
                print 'Processing page -', page.id, page
                kwargs['instance'] = page
                updated, page.content = self.process_content(
                                        page.content, **kwargs)
                if updated:
                    page.save()
        elif app_name == 'jobs':
            from tendenci.addons.jobs.models import Job
            jobs = Job.objects.all()
            for job in jobs:
                print 'Processing job -', job.id, job
                kwargs['instance'] = job
                updated, job.description = self.process_content(
                                        job.description, **kwargs)
                if updated:
                    job.save()
        elif app_name == 'events':
            from tendenci.addons.events.models import Event, Speaker
            events = Event.objects.all()
            for event in events:
                print 'Processing event -', event.id, event
                kwargs['instance'] = event
                updated, event.description = self.process_content(
                                        event.description, **kwargs)
                if updated:
                    event.save()

            # speakers
            speakers = Speaker.objects.all()
            for speaker in speakers:
                print 'Processing event speaker -', speaker.id, speaker
                kwargs['instance'] = speaker
                updated, speaker.description = self.process_content(
                                        speaker.description, **kwargs)
                if updated:
                    speaker.save()

        print "\nTotal links updated for %s: " % app_name, self.total_count

    def process_content(self, content, **kwargs):
        self.replace_dict = {}

        matches = self.p.findall(content)
        print '... ', len(matches), 'matches found.'

        for match in matches:
            link = match[1]
            self.process_link(link, **kwargs)

        # find and replace urls
        if self.replace_dict:
            updated = True
            for url_find, url_repl in self.replace_dict.iteritems():
                content = content.replace(url_find, url_repl)
            count = self.replace_dict.__len__()
            print '...', count, 'link(s) replaced.'
            self.total_count += count
        else:
            updated = False

        return updated, content

    def process_link(self, link, **kwargs):
        # check if this is a broken link
        # the link can from three different sources:
        # this site:
        #    absolute url
        #    relative url
        # the src site:
        #    absolute url
        # the other sites:
        #    absolute url

        # handle absolute url
        o = urlparse(link)
        relative_url = urllib.quote(urllib.unquote(o.path))
        hostname = o.hostname

        # skip if link is external other than the src site.
        if hostname and hostname not in (self.site_domain,
                                         self.site_domain.lstrip('www.'),
                                         self.src_domain,
                                         self.src_domain.lstrip('www.')):
            if not self.link_exists(relative_url, hostname):
                print '-- External broken link: ', link
            return

        # if link doesn't exist on the site but on the src
        if not self.link_exists(relative_url, self.site_domain):
            if self.link_exists(relative_url, self.src_domain):
                url = '%s%s' % (self.src_url, relative_url)
                # go get from the src site
                tfile = self.save_file_from_url(url, kwargs.get('instance'))
                self.replace_dict[link] = tfile.get_absolute_url()
            else:
                print '** Broken link - ', link, "doesn't exist on both sites."

    def link_exists(self, relative_link, domain):
        """
        Check if this link exists for the given domain.

        example of a relative_link:
        /images/newsletter/young.gif
        """
        conn = httplib.HTTPConnection(domain)
        conn.request('HEAD', relative_link)
        res = conn.getresponse()
        conn.close()

        return res.status in (200, 304)

    def save_file_from_url(self, url, instance):
        file_name = os.path.basename(urllib.unquote(url).replace(' ', '_'))
        tfile = TFile()
        tfile.name = file_name
        tfile.content_type = ContentType.objects.get_for_model(instance)
        tfile.object_id = instance.id
        if hasattr(instance, 'creator'):
            tfile.creator = instance.creator
        if hasattr(instance, 'creator_username'):
            tfile.creator_username = instance.creator_username
        if hasattr(instance, 'owner'):
            tfile.owner = instance.owner
        if hasattr(instance, 'owner_username'):
            tfile.owner_username = instance.owner_username

        file_path = file_directory(tfile, tfile.name)
        tfile.file.save(file_path, ContentFile(urllib2.urlopen(url).read()))
        tfile.save()
        return tfile
