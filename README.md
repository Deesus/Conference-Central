## Conference Central
###### A conference scheduling application built on Google's _App Engine_

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1.  Update the value of `application` in `app.yaml` to the app ID you
    have registered in the App Engine admin console and would like to use to host
    your instance of this sample.
2.  Update the values at the top of `settings.py` to
    reflect the respective client IDs you have registered in the
    [Developer Console][4].
3.  Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
4.  (Optional) Mark the configuration files as unchanged as follows:
    `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
5.  Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting
    your local server's address (by default [localhost:8080][5].)
6.  Generate your client library(ies) with [the endpoints tool][6].
7.  Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
___________________________________________________________


## Example of Deployed App
A deployed version of the *Conference Central* app can be accessed at [https://scalable-apps-990.appspot.com](https://scalable-apps-990.appspot.com). 

You can test the endpoints (of this deployed app) from Google's endpoints explorer: [https://scalable-apps-990.appspot.com/_ah/api/explorer](https://scalable-apps-990.appspot.com/_ah/api/explorer).

Addendum: You can likewise test the endpoints of your own app by replacing `scalable-apps-990` from the above url with your app's registered ID or localhost. E.g. to use Google's api endpoints explorer on a local version of your app, you can visit [http://localhost:8080/_ah/api/explorer](http://localhost:8080/_ah/api/explorer) on your browser.


## Task 1: Add Sessions to a Conference
For this task, we define the following endpoints regarding conference sessions:

```
getConferenceSessions(websafeConferenceKey)
getConferenceSessionsByType(websafeConferenceKey, typeOfSession)
getSessionsBySpeaker(speaker)
createSession(SessionForm, websafeConferenceKey)
```

Overall, I kept in-line with the structure and style of Udacity's preexisting code. The basis of my design choices for these session endpoints was to emulate the style and functionality of the Conference Objects; because the session methods are functionally similar to the conference methods, the code for sessions is similar to the code for conferences. E.g. the `_createSessionObject` method is based on the `_createConferenceObject` method. Likewise, the `Session` class (kind) emulates the `Conference` kind, and with the exception of "speaker" and "highlights" properties (which is specific to sessions), the `Session` kind contains similar properties and retains similar data types:

```
name            = ndb.StringProperty(required=True)
date            = ndb.DateProperty()
speaker         = ndb.StringProperty()
startTime       = ndb.TimeProperty()
typeOfSession   = ndb.StringProperty()
duration        = ndb.TimeProperty()
highlights      = ndb.StringProperty(repeated=True)
```

The choice for data types was fairly clear-cut: the standard "StringProperty" was used to for various names (names of the session, names of speakers, etc.); "date" is represented by "DateProperty"; "time" and "duration" are represented with the "Time" data type; and since there can be multiple highlights in a session (i.e. an array of values), we specify `repeated=True`.

The 'GET' methods, `getConferenceSessions` and `getConferenceSessionsByType` reuse the `_query_sessions` helper method. Since the Session object are children of Conferences (i.e. each conference contains one or more session), sessions can be easily queried by accessing the conference key and filtering when necessary.


## Task 2: Add Sessions to User Wishlist
The endpoints `addSessionToWishlist(SessionKey)` and `getSessionsInWishlist()` enable the user to save sessions of interest in their profile (i.e. in the `Profile` entity). The user can add any session (not just the ones he has registered for) into the wishlist, so long as he is logged in. Each time the user adds a session to his wishlist, the session key is appended to the `wishListKeys` field. Because the wishlist is dependent on each individual user (and not, for example, the conference) it would make the most sense to implement the wishlist as a field within the Profile entity:
```
class Profile(ndb.Model):
	wishListKeys = ndb.StringProperty(repeated=True)
	# ...
```


## Task 3: Work on indexes and queries
#### Query Related Problem:
Datastore has two query restrictions:
1. An inequality filter can be applied to at most one property.
2. A property with an inequality filter must be sorted first.

If we wished to query for "all non-workshop sessions before 7 pm," we would normally apply two restrictions: `Session.typeOfSession != 'workshop'` and `Session.startTime < '19:00'`. However, using these two restrictions is prohibited since they are inequalities and are being applied to the kind's property.
One solution would be to create two different queries, then we can check which items intersect in the two sets:
```
# Create two separate queries:
session_type = Session.query().filter(Session.typeOfSession != 'workshop')
session_time = Session.query().filter(Session.startTime < '19:00')

# Check if items in one is contained in another:
output.append(x) for x in session_type if x in session_time
```

#### Come up with 2 Additional Queries:
The two queries I have implemented in the *Conference Central* app are:
```
getSessionsInWishlistByType(typeOfSesion)
getSessionsInWishlistBySpeaker(Speaker)
```
As the names imply, the `getSessionsInWishlistByType` method searches the user's wishlist for sessions and then filters the result by the type of session and the `getSessionsInWishlistBySpeaker` method returns the user's wishlist sessions by the speaker's name. The purpose/benefit of the two methods is to enable the user to see only specific sessions in his wishlist, abating the need to peruse through a large list of results.

The two additional queries implement the solution to the aforementioned 'query related problem.' For example,  the `getSessionsInWishlistByType` method 
queries all session objects (filtered by request type) and also fetches all items in the user's wishlist. We then loop through the array and search for intersections between the two arrays:
```
return SessionForms(items=[self._copySessionToForm(x) for x in wish_list_sessions if x in requested_session_type]
```


## Task 4: Add a Task

The private `_createSessionObject` method is modified to add a task to the taskqueue -- this task is handled by the `CheckFeaturedSpeaker` class. The `_createSessionObject` method passes the speaker name along with wsck [conference key] to `CheckFeaturedSpeaker`. When a session is added by the user, and this session includes the name of a speaker, the `CheckFeaturedSpeaker` checks [iterates through] the session's conference for additional entries of the given speaker. If multiple entries [2 or more] of the speaker are found, this speaker is set as the "featured speaker" (along with the names of the sessions the speaker is partaking in) in the app's Memcache. Conversely, the `getFeaturedSpeaker(ConferenceKey)` endpoint returns the featured speaker (if one exists) for the given conference.
In creating the taskqueue for `CheckFeaturedSpeaker`, I sought to emulate and extend the extant code in `SendConfirmationEmailHandler` -- which also uses a taskqueue to complete certain time-insensitive jobs. 
