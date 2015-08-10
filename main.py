#!/usr/bin/env python
import webapp2
from google.appengine.api import app_identity, mail, memcache
from google.appengine.ext import ndb
from conference import ConferenceApi
from conference import MEMCACHE_FEATURED_SPEAKER_KEY
from models import Session


class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""

        ConferenceApi._cacheAnnouncement()


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""

        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )


class CheckFeaturedSpeaker(webapp2.RequestHandler):
    def post(self):
        """Checks the speakers in given conference and if it finds more than 1
        entry of the speaker, it sets a memcache entry to the speaker and the
        session names the speaker is in.
        """

        speaker_ = self.request.get('speaker')
        if speaker_ != "none":
            memcache_output = []
            wsck = self.request.get('wsck')
            conf = ndb.Key(urlsafe=wsck).get()

            # search sessions for multiple instances of the same speaker:
            sessions_in_conf = Session.query(ancestor=conf.key)
            for x in sessions_in_conf:
                # if we find a match, add session to output:
                if x.speaker == speaker_:
                    memcache_output.append(str(x.name))

            # if memcache_output is greater than 1, we have a featured speaker:
            if len(memcache_output) > 1:
                # create unique memcache key for conference (using conf key):
                memcache_key = MEMCACHE_FEATURED_SPEAKER_KEY + str(wsck)

                # cast memcache_output as string:
                memcache_output = ', '.join(memcache_output)

                # set memcache on datastore using key, speaker, and output:
                memcache.set(memcache_key, "Featured Speaker: {}. Sessions: {}"
                                           "".format(speaker_,
                                                     memcache_output))

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/set_featured_speaker', CheckFeaturedSpeaker)
], debug=True)
