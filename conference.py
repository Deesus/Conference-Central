#!/usr/bin/env python

"""

conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $
created by wesc on 2014 apr 21
"""

__authors__ = ['wesc+api@google.com (Wesley Chun)',
               'eyeofpie@gmail.com (Dee Reddy)']

from datetime import datetime
from datetime import date as date_

import endpoints
from settings import WEB_CLIENT_ID
from utils import getUserId

from protorpc import messages, message_types, remote

from google.appengine.ext import ndb
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from models import Profile, ProfileMiniForm, ProfileForm
from models import TeeShirtSize
from models import Conference, ConferenceForm, ConferenceForms, ConferenceQueryForms
from models import Session, SessionForm, SessionForms
from models import BooleanMessage
from models import ConflictException
from models import StringMessage

MEMCACHE_ANNOUNCEMENTS_KEY = "Recent Announcements"
MEMCACHE_FEATURED_SPEAKER_KEY = "featured_speaker_"
EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city":             "Default City",
    "maxAttendees":     0,
    "seatsAvailable":   0,
    "topics":           ["Default", "Topic"],
}

DEFAULTS_SESSION = {
    "date":             str(date_.today()),
    "speaker":          "none",
    "startTime":        "01:00",
    "typeOfSession":    "Default Session",
    "duration":         "00:00",
    "highlights":       ["Default", "Highlights"]
}

OPERATORS = {
    'EQ':   '=',
    'GT':   '>',
    'GTEQ': '>=',
    'LT':   '<',
    'LTEQ': '<=',
    'NE':   '!='
}

FIELDS = {
    'CITY': 'city',
    'TOPIC': 'topics',
    'MONTH': 'month',
    'MAX_ATTENDEES': 'maxAttendees'
}

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1)
)

SESSION_GET_REQUEST_BY_TYPE = endpoints.ResourceContainer(
    typeOfSession       =messages.StringField(1),
    websafeConferenceKey=messages.StringField(2)
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1)
)

SESSION_SPEAKER_REQUEST = endpoints.ResourceContainer(
    speaker = messages.StringField(1)
)

SESSION_WISH_LIST_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1)
)

WISHLIST_GET_REQUEST_BY_TYPE = endpoints.ResourceContainer(
    typeOfSession=messages.StringField(1)
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference',
               version='v1',
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

######################################
#           Profile Objects          #
######################################

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name,
                            getattr(TeeShirtSize,
                                    getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore,
        creating new one if non-existent.
        """

        # ensure user is logged in:
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException("Please Login")

        # get Profile entity from datastore by using get() on the key:
        p_key = ndb.Key(Profile, getUserId(user))
        profile = p_key.get()
        if not profile:
            profile = Profile(
                key             =p_key,
                displayName     =user.nickname(),
                mainEmail       =user.email(),
                teeShirtSize    =str(TeeShirtSize.NOT_SPECIFIED),
            )
            # save the profile to datastore:
            profile.put()
        return profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""

        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            # put the modified profile to datastore
            prof.put()
        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile',
                      http_method='GET',
                      name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile',
                      http_method='POST',
                      name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

######################################
#         Conference Objects         #
######################################

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""

        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"],
                                                   filtr["operator"],
                                                   filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""

        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name:
                     getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous
                # filters; disallow the filter if inequality was performed on a
                # different field before; track the field on which the
                # inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""

        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning
        ConferenceForm/request."""

        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name:
                getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model &
        # outbound Message):
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects;
        # set month based on start_date:
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID:
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent:
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID:
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm:
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email'
                      )
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict:
        data = {field.name:
                getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm,
                      path='conference',
                      http_method='POST',
                      name='createConference')
    def createConference(self, request):
        """Create new conference."""

        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT',
                      name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET',
                      name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""

        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""

        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [
            (ndb.Key(Profile, conf.organizerUserId)) for conf in conferences
            ]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf,
                names[conf.organizerUserId]) for conf in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='queryConferencesCreated',
                      http_method='POST',
                      name='queryConferencesCreated')
    def queryConferencesCreated(self, request):
        """Return conferences created by CURRENT user."""

        # ensure user is logged in:
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException("Please Login")

        # create ancestor query for all key matches for this user
        p_key = ndb.Key(Profile, getUserId(user))
        conferences = Conference.query(ancestor=p_key)
        profile = p_key.get()
        display_name = profile.displayName

        return ConferenceForms(
            items=[
                self._copyConferenceToForm(x, display_name)
                for x in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET',
                      name='filterPlayground')
    def filterPlayground(self, request):
        """Test the filter API here"""

        query_object = Conference.query()
        query_object = query_object.filter(Conference.city == 'London')
        query_object = query_object.filter(
            Conference.topics == "Medical Innovations")
        query_object = query_object.filter(Conference.seatsAvailable > 23)

        return ConferenceForms(
            items=[self._copyConferenceToForm(x, "") for x in query_object]
        )

######################################
#            Registration            #
######################################

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""

        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST',
                      name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""

        return self._conferenceRegistration(request)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET',
                      name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""

        # get user profile
        prof = self._getProfileFromUser()

        # get conferenceKeysToAttend from profile.
        array_conf_keys = [ndb.Key(urlsafe=wsck)
                           for wsck in prof.conferenceKeysToAttend]

        # fetch conferences from datastore:
        conferences = ndb.get_multi(array_conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId)
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf, names[conf.organizerUserId]) for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE',
                      name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""

        return self._conferenceRegistration(request, reg=False)


######################################
#           Announcements            #
######################################

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """

        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET',
                      name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""

        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

######################################
#               Sessions             #
######################################

    def _copySessionToForm(self, session_):
        """Copy fields from Session to SessionForm"""

        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session_, field.name):
                # convert date, time, and duration to string:
                if field.name == "date" or field.name == "startTime" or \
                        field.name == "duration":
                    setattr(sf, field.name, str(getattr(session_, field.name)))
                # all other fields are simply copied:
                else:
                    setattr(sf, field.name, getattr(session_, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session_.key.urlsafe())
            elif field.name == "websafeConferenceKey":
                setattr(sf, field.name, session_.key.parent().urlsafe())

        sf.check_initialized()
        return sf

    def _query_sessions(self, request):
        """Helper function for getting sessions"""

        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s'
                % request.websafeConferenceKey)

        # find sessions:
        sessions_ = Session.query(ancestor=conf.key)

        return sessions_

    def _createSessionObject(self, request):
        """Helper function to create session object and check featured speaker.

        Creates session object, returning SessionForm object. Also checks the
        speakers in given conference and if it finds more than one entry of
        the speaker, it sets a memcache entry to the speaker and the
        session names the speaker is in.
        """

        # ensure user is logged in:
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException("Authorization required")
        user_id = getUserId(user)

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # check to make sure user is also the creator of object:
        if user_id != conf.organizerUserId:
            raise endpoints.UnauthorizedException(
                "Only the creator of the conference may add sessions.")

        # ensure session's name was specified:
        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into hash:
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['websafeConferenceKey']

        # add default values for those missing (both data model & outbound
        # Message):
        for df in DEFAULTS_SESSION:
            if data[df] in (None, []):
                data[df] = DEFAULTS_SESSION[df]
                setattr(request, df, DEFAULTS_SESSION[df])

        # convert date from string to Date object:
        if data['date']:
            data['date'] = datetime.strptime(
                data['date'][:10], "%Y-%m-%d").date()
        # convert startTime from string to Time object:
        if data['startTime']:
            data['startTime'] = datetime.strptime(
                data['startTime'][:10], "%H:%M").time()
        # convert duration from string to Time object:
        if data['duration']:
            data['duration'] = datetime.strptime(
                data['duration'][:10], "%H:%M").time()

        # check for featured speaker in conference:
        if data['speaker'] != "none":
            memcache_output = ''
            sessions_in_conf = self._query_sessions(request)
            # search sessions for multiple instances of the same speaker:
            for x in sessions_in_conf:
                # if we find a match (the speaker exists in another session):
                if x.speaker == data['speaker']:
                    # add session to output:
                    memcache_output += data['name'] + " "

            # if we have memcache_output, we have a featured speaker:
            if memcache_output:
                # append the newly added session to output string:
                memcache_output += data['name']

                # create unique memcache key for conference
                # (using conference key):
                memcache_key = MEMCACHE_FEATURED_SPEAKER_KEY + str(wsck)

                # set memcache on datastore using key, speaker, and output:
                memcache.set(memcache_key, "Featured Speaker: {}. Sessions: {}"
                                           "".format(data['speaker'],
                                                     memcache_output))

        # make Conference key:
        c_key = conf.key
        # allocate new Session ID with Conference key as parent:
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        # make Session key from ID:
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key

        # create Session & return (modified) SessionForm:
        Session(**data).put()

        # we want 'models.SessionForm':
        session_ = s_key.get()
        return self._copySessionToForm(session_)

    @endpoints.method(SESSION_POST_REQUEST, SessionForm,
                      path='conference/{websafeConferenceKey}/session/new',
                      http_method="POST",
                      name="createSession")
    def createSession(self, request):
        """Create new session -- open to the organizer of the conference"""

        return self._createSessionObject(request)

    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/sessions',
                      http_method='GET',
                      name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return sessions given the conference (by websafeConferenceKey)."""

        # find sessions:
        sessions_ = self._query_sessions(request)

        # return an array of individual sessions-form objects per conference:
        return SessionForms(
            items=[self._copySessionToForm(x) for x in sessions_]
        )

    @endpoints.method(SESSION_GET_REQUEST_BY_TYPE, SessionForms,
                      path='conference/{websafeConferenceKey}/sessions/type',
                      http_method='GET',
                      name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Given a conference (websafeConferenceKey), return all sessions of a
        specified type (e.g. lecture, keynote, workshop).
        """

        # find sessions:
        sessions_ = self._query_sessions(request)

        # filter results:
        sessions_ = sessions_.filter(
            Session.typeOfSession == request.typeOfSession
        )

        # return an array of individual sessions-form objects per conference:
        return SessionForms(
            items=[self._copySessionToForm(x) for x in sessions_]
        )

    @endpoints.method(SESSION_SPEAKER_REQUEST, SessionForms,
                      path='sessions/speaker',
                      http_method='GET',
                      name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Given a speaker, return all sessions given by this particular
        speaker, across all conferences.
        """

        # find sessions:
        sessions_ = Session.query(Session.speaker == request.speaker)

        # order alphabetically:
        sessions_ = sessions_.order(Session.name)

        # return an array of sessions-form objects:
        return SessionForms(
            items=[self._copySessionToForm(x) for x in sessions_]
        )

######################################
#               Wishlist             #
######################################

    @endpoints.method(SESSION_WISH_LIST_POST_REQUEST, BooleanMessage,
                      path='addToWishlist',
                      http_method='POST',
                      name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Adds the session to the user's list of sessions they are
        interested in attending"""

        retval = None

        # ensure user is logged in, and get profile:
        profile_ = self._getProfileFromUser()

        # get session by websafe key:
        wsck = request.websafeSessionKey
        session_ = ndb.Key(urlsafe=wsck).get()
        # check if session exists:
        if not session_:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % wsck)

        # register:
        # check if user already added to wishlist; otherwise add:
        if wsck in profile_.wishListKeys:
            raise ConflictException(
                "You have already have this session in your wishlist")
        else:
            profile_.wishListKeys.append(wsck)
            retval = True

        # write things back to the datastore & return
        profile_.put()
        session_.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='wishlist',
                      http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Query for all the sessions in a conference that the user is
        interested in."""

        # ensure user is logged in, and get profile:
        profile_ = self._getProfileFromUser()

        # get wishListKeys (array of session keys) from profile:
        session_keys = [ndb.Key(urlsafe=wsck)
                        for wsck in profile_.wishListKeys]

        # fetch sessions from datastore:
        wish_list_sessions = ndb.get_multi(session_keys)

        # return set of SessionForm objects per Session:
        return SessionForms(
            items=[self._copySessionToForm(x) for x in wish_list_sessions]
        )

######################################
#         Additional Queries         #
######################################

    @endpoints.method(WISHLIST_GET_REQUEST_BY_TYPE, SessionForms,
                      path='wishlist/type',
                      http_method='GET',
                      name='getSessionsInWishlistByType')
    def getSessionsInWishlistByType(self, request):
        """Return user's wishlist, filtered by session type."""

        # ensure user is logged in, and get profile:
        profile_ = self._getProfileFromUser()

        # get wishListKeys (array of session keys) from profile:
        session_keys = [ndb.Key(urlsafe=wsck)
                        for wsck in profile_.wishListKeys]

        # fetch sessions in wishlist:
        wish_list_sessions = ndb.get_multi(session_keys)

        # query ALL sessions (not just ones in wishlist), filtered by type:
        requested_session_type = Session.query(
            Session.typeOfSession == request.typeOfSession)

        # If any of the user's wishlist session matches the session query,
        # append this session to result. Return result as SessionForms object:
        return SessionForms(
            items=[self._copySessionToForm(x) for x in wish_list_sessions
                   if x in requested_session_type]
        )

    @endpoints.method(SESSION_SPEAKER_REQUEST, SessionForms,
                      path='wishlist/speaker',
                      http_method='GET',
                      name='getSessionsInWishlistBySpeaker')
    def getSessionsInWishlistBySpeaker(self, request):
        """Return user's wishlist, filtered by speaker."""

        # ensure user is logged in, and get profile:
        profile_ = self._getProfileFromUser()

        # get wishListKeys (array of session keys) from profile:
        session_keys = [ndb.Key(urlsafe=wsck)
                        for wsck in profile_.wishListKeys]

        # fetch sessions in wishlist:
        wish_list_sessions = ndb.get_multi(session_keys)

        # query ALL sessions (not just ones in wishlist), filtered by speaker:
        requested_session_type = Session.query(
            Session.speaker == request.speaker)

        # If any of the user's wishlist session matches the session query,
        # append this session to result. Return result as SessionForms object:
        return SessionForms(
            items=[self._copySessionToForm(x) for x in wish_list_sessions
                   if x in requested_session_type]
        )

######################################
#          Featured Speaker          #
######################################

    @endpoints.method(CONF_GET_REQUEST, StringMessage,
                      path='featuredSpeaker',
                      http_method='GET',
                      name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Returns featured speaker and the sessions he's partaking in from
        memcache"""

        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # create memcache key based on conf key:
        memcache_key_ = MEMCACHE_FEATURED_SPEAKER_KEY + str(wsck)

        # try to find entry in memcache:
        output_ = memcache.get(memcache_key_)
        if output_:
            return StringMessage(data=memcache.get(memcache_key_))
        else:
            return StringMessage(
                data="There are no featured speakers for this conference.")

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

# registers API
api = endpoints.api_server([ConferenceApi])
