# Synology virtual album for Home Assistant
This integration is for Synology Photos users to create a virtual album in the Home Assistant media sources. Adding Synology Photos to media sources is something that can be accomplished with the built in Synology DSM integration for Home Assistant (and in fact it's required for this integration), but this adds the ability to pull from multiple albums into one, and chose a random selection each day to feature.

# Setup
- This integration uses the [Synology DSM](https://my.home-assistant.io/redirect/config_flow_start?domain=synology_dsm) integration, so you must have that set up first.
- Add the Synology Virtual Album integration and choose your DSM. You can also choose a name for your virtual album, or accept the default.
- On the next page, choose the source album(s) that will contribute to your virtual album.
  - Choose the maximum amount of items for your virtual album. If you're going to be refreshing the contents of the album daily you'll likely want to go with a low number here, 150 or so.
  - Choose the maximum percentage of items from the current day in any year that will be included in the album. This is intended for the case where you're refreshing the contents of the album daily, and want to be able to reminisce about what you were doing on this day in past years. If you're not refreshing the album daily, or don't want a bias towards items from the current date, you can set this to zero to disable it.
  - Choose the maximum percentage of items from the coming week. This is the same as the current day option, but for surfacing "coming soon" anniversaries. Similarly, you can disable it by setting this to zero.
  - If you are using your virtual album with [WallPanel](https://github.com/j-a-n/lovelace-wallpanel), and have configured an entity to track the current photo, select it here to add some additional entities useful for the overlay info.

# Usage
Once you've set up the integration you should have an entry called Synology Virtual Album, and inside that a folder with the name you chose for your album (Slideshow by default). To rebuild your virtual album you can use the service Rebuild Virtual Album. For example, to rebuild the album every day at 1 am you could use an automation like this:
```yaml
alias: Rebuild Slideshow
description: ""
triggers:
  - trigger: time
    at: "01:00:00"
actions:
  - action: synology_virtual_album.rebuild_virtual_album
    metadata: {}
    data:
      album: your_album_id
mode: single
```

# WallPanel
If you're using the virtual album as the screensaver in WallPanel there are a few useful features. Set up an input text helper to hold the current screensaver image and select it in the settings. That will cause two additional entities to be created: a sensor that holds the capture time of the current image, and a device tracker with the location of the current image, based on the exif data. Additionally, each entity has attributes with additional data. The date sensor has an attribute called description, which holds a text description of how long ago the photo was taken. This is the same as what you would get with the following template:
```
{{ time_since(states('sensor.slideshow_current_photo_date') | as_datetime) }}
```
The only difference is if the photo was taken today on a previous year it will say "5 years ago today", or "5 years ago this week".

The device tracker additional data contains all of the geocoded fields Synology Photos stores. Here's a template sensor to combine these two entities into something you can put on your screensaver overlay.
```jinja
{{ state_attr("sensor.slideshow_current_photo_date", "Description") -}}
{%- if state_attr("device_tracker.slideshow_current_photo_location", "city") -%}
   , {{ state_attr("device_tracker.slideshow_current_photo_location", "city") }}
{%- elif state_attr("device_tracker.slideshow_current_photo_location", "town") -%}
   , {{ state_attr("device_tracker.slideshow_current_photo_location", "town") }}
{%- elif state_attr("device_tracker.slideshow_current_photo_location", "county") -%}
   , {{ state_attr("device_tracker.slideshow_current_photo_location", "county") -}}
{% endif -%}
{%- if state_attr("device_tracker.slideshow_current_photo_location", "state") -%}
   , {{ state_attr("device_tracker.slideshow_current_photo_location", "state") }}
{% endif -%}
```
Output:
> 5 years ago today, Austin, Texas

## WallPanel cache invalidation
WallPanel caches the contents of the media source and only refreshes them once media_list_update_interval seconds have passed (by default, once an hour). If you refresh the album you'll have missing images until the next refresh. You can set the update interval to a low value to work around that, but another solution is to use the WallPanel profile feature to force a refresh. If you're not currently using profiles you can add one just for forcing the refresh. Create an input text helper to store the profile name, and add something like this to your WallPanel config:
```yaml
profile_entity: input_text.wallpanel_profile
profiles:
  default:
    image_url: media-source://synology_virtual_album/slideshow
```
Then, when you're rebuilding your virtual album, set the profile to an invalid value, then back to your default value, to force a refresh.
```yaml
alias: Rebuild Slideshow
description: ""
triggers:
  - trigger: time
    at: "01:00:00"
actions:
  - action: input_text.set_value
    metadata: {}
    data:
      value: reload
    target:
      entity_id: input_text.wallpanel_profile
    alias: Set invalid Wallpanel profile
  - action: synology_virtual_album.rebuild_virtual_album
    metadata: {}
    data:
      album: your_album_id
  - action: input_text.set_value
    metadata: {}
    data:
      value: default
    target:
      entity_id: input_text.wallpanel_profile
    alias: Set default Wallpanel profile
mode: single
```
Use Control + Shift + m to toggle the tab key moving focus. Alternatively, use esc then tab to move to the next interactive element on the page.
Attach files by dragging & dropping, selecting or pasting them.
Editing synology_virtual_album/README.md at main · colings/synology_virtual_album
