#!/usr/bin/env python

"""models.py
Udacity conference server-side Python App Engine data & ProtoRPC models

$Id: models.py,v 1.1 2014/05/24 22:01:10 wesc Exp $

created/forked from conferences.py by wesc on 2014 may 24
"""

__authors__ = ['wesc+api@google.com (Wesley Chun)',
               'eyeofpie@gmail.com (Dee Reddy)']

import httplib
import endpoints
from protorpc import messages
from google.appengine.ext import ndb

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


class BooleanMessage(messages.Message):
    """Outbound Boolean value message. Needed for conference registration"""

    data = messages.BooleanField(1)


class ConflictException(endpoints.ServiceException):
    """Exception mapped to HTTP 409 response"""

    http_status = httplib.CONFLICT


class ProfileMiniForm(messages.Message):
    """Update Profile form message"""

    displayName     = messages.StringField(1)
    teeShirtSize    = messages.EnumField('TeeShirtSize', 2)


class Profile(ndb.Model):
    """User profile object"""

    displayName             = ndb.StringProperty()
    mainEmail               = ndb.StringProperty()
    teeShirtSize            = ndb.StringProperty(default='NOT_SPECIFIED')
    conferenceKeysToAttend  = ndb.StringProperty(repeated=True)
    wishListKeys            = ndb.StringProperty(repeated=True)


class ProfileForm(messages.Message):
    """Profile outbound form message"""

    userId          = messages.StringField(1)
    displayName     = messages.StringField(2)
    mainEmail       = messages.StringField(3)
    teeShirtSize    = messages.EnumField('TeeShirtSize', 4)
    wishListKeys    = messages.StringField(5, repeated=True)


class TeeShirtSize(messages.Enum):
    """T-shirt size enumeration value"""

    NOT_SPECIFIED = 1
    XS_M = 2
    XS_W = 3
    S_M = 4
    S_W = 5
    M_M = 6
    M_W = 7
    L_M = 8
    L_W = 9
    XL_M = 10
    XL_W = 11
    XXL_M = 12
    XXL_W = 13
    XXXL_M = 14
    XXXL_W = 15


class Conference(ndb.Model):
    """Conference object"""

    name            = ndb.StringProperty(required=True)
    description     = ndb.StringProperty()
    organizerUserId = ndb.StringProperty()
    topics          = ndb.StringProperty(repeated=True)
    city            = ndb.StringProperty()
    startDate       = ndb.DateProperty()
    month           = ndb.IntegerProperty()
    endDate         = ndb.DateProperty()
    maxAttendees    = ndb.IntegerProperty()
    seatsAvailable  = ndb.IntegerProperty()


class ConferenceForm(messages.Message):
    """Conference outbound form message"""

    name                    = messages.StringField(1)
    description             = messages.StringField(2)
    organizerUserId         = messages.StringField(3)
    topics                  = messages.StringField(4, repeated=True)
    city                    = messages.StringField(5)
    startDate               = messages.StringField(6)
    month                   = messages.IntegerField(7)
    maxAttendees            = messages.IntegerField(8)
    seatsAvailable          = messages.IntegerField(9)
    endDate                 = messages.StringField(10)
    websafeKey              = messages.StringField(11)
    organizerDisplayName    = messages.StringField(12)


class ConferenceForms(messages.Message):
    """Multiple Conference outbound form message"""

    items = messages.MessageField(ConferenceForm, 1, repeated=True)


class ConferenceQueryForm(messages.Message):
    """Conference query inbound form message"""

    field       = messages.StringField(1)
    operator    = messages.StringField(2)
    value       = messages.StringField(3)


class ConferenceQueryForms(messages.Message):
    """Multiple ConferenceQueryForm inbound form message"""

    filters = messages.MessageField(ConferenceQueryForm, 1, repeated=True)


class StringMessage(messages.Message):
    """Outbound (single) string message"""

    data = messages.StringField(1, required=True)


######################################
#              Sessions              #
######################################


class Session(ndb.Model):
    """Conference Sessions object"""


    name            = ndb.StringProperty(required=True)
    date            = ndb.DateProperty()
    speaker         = ndb.StringProperty()
    startTime       = ndb.TimeProperty()
    typeOfSession   = ndb.StringProperty()
    duration        = ndb.TimeProperty()
    highlights      = ndb.StringProperty(repeated=True)


class SessionForm(messages.Message):
    """Session outbound form message"""

    name            = messages.StringField(1)
    date            = messages.StringField(2)
    speaker         = messages.StringField(3)
    startTime       = messages.StringField(4)
    typeOfSession   = messages.StringField(5)
    duration        = messages.StringField(6)
    highlights      = messages.StringField(7, repeated=True)
    websafeKey      = messages.StringField(8)


class SessionForms(messages.Message):
    """Multiple Conference outbound form message"""

    items = messages.MessageField(SessionForm, 1, repeated=True)
