import datetime

TRIGGERS = {}

@time_trigger('startup')
def firefly():
    log.info("Firefly is starting up...")
    
    for room in pyscript.app_config["rooms"]:
        get_temp_target(room)

        room_triggers = trigger_factory(room)
        TRIGGERS[room] = room_triggers

    log.info("Firefly is ready!")


def weekday_to_dow(weekday):
    if weekday == "monday":
        return 1
    elif weekday == "tuesday":
        return 2
    elif weekday == "wednesday":
        return 3
    elif weekday == "thursday":
        return 4
    elif weekday == "friday":
        return 5
    elif weekday == "saturday":
        return 6

    return 0


def dow_to_weekday(dow):
    return ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][dow]


def get_cron(weekday, time):
    h, m = time.split(":")
    dow = weekday_to_dow(weekday)

    return f"cron({m} {h} * * {dow})"


def get_timestamp(h, m):
    return int(h) * 60 + int(m)


def get_time():
    now = datetime.datetime.now().time()
    dow = datetime.datetime.today().isoweekday() % 7
    
    h, m, q = str(now).split(":", 3)
    timestamp = get_timestamp(h, m)

    return dow, timestamp


def get_current_schedule(room, weekday, current_timestamp):
    current_schedule = 0

    for time in pyscript.app_config["rooms"][room][weekday]:
        h, m = time.split(":")
        if get_timestamp(h, m) <= current_timestamp:
            current_schedule = time

    return current_schedule


def get_temp_target(room):
    dow, timestamp = get_time()
    weekday = dow_to_weekday(dow)

    if weekday not in pyscript.app_config["rooms"][room] and weekday in ["saturday", "sunday"] and "weekend" in pyscript.app_config["rooms"][room]:
        weekday = "weekend"
    elif weekday not in pyscript.app_config["rooms"][room]:
        weekday = "default"
    
    current_schedule = get_current_schedule(room, weekday, timestamp)
    target = pyscript.app_config["rooms"][room][weekday][current_schedule]

    try:
        scheduled = target
        actual = state.getattr(f"climate.{room}")["temperature"]
        home = is_home()
        matching = "on" if scheduled == actual or not home else "off"
        state.set(f"firefly.{room}", matching, {"actual_target": actual, "scheduled_target": scheduled, "mode": "home" if home else "away"})
    except:
        pass

    return target


def is_home():
    return int(state.get(pyscript.app_config["zone"])) > 0 or state.get(pyscript.app_config["preheat"]) == "on"


def trigger_factory(room):
    weekdays = {
        "monday": [],
        "tuesday": [],
        "wednesday": [],
        "thursday": [],
        "friday": [],
        "saturday": [],
        "sunday": [],
    }

    for day in [day for day in pyscript.app_config["rooms"][room]]:
        if day == "default":
            for weekday in [weekday for weekday in weekdays if not weekdays[weekday]]:
                weekdays[weekday] = create_triggers(room, day, weekday)
        elif day == "weekend":
            for weekday in [weekday for weekday in weekdays if weekday in ["saturday", "sunday"]]:
                weekdays[weekday] = create_triggers(room, day, weekday)
        elif day in weekdays.keys():
            weekdays[weekday] = create_triggers(room, day, day)

    return weekdays


def create_triggers(room, day, weekday):
    time_triggers = []

    for time in [time for time in pyscript.app_config["rooms"][room][day]]:
        log.debug(f"Firefly is creating a trigger in {room} for {weekday} at {time}") 

        @time_trigger(get_cron(weekday, time))
        def heat_change():
            firefly_update_heating(room)

        time_triggers.append(heat_change)

    return time_triggers


@service
def firefly_update_heating(room):
    current = state.getattr(f"climate.{room}")["temperature"]
    target = get_temp_target(room)
    home = is_home()

    if current == target:
        log.info(f"Firefly will keep the temperature in {room} at {current}.")
        preset = "home" if home else "away"
        if state.getattr(f"climate.{room}")["preset_mode"] != preset:
            service.call("climate", "set_preset_mode", entity_id=f"climate.{room}", preset_mode=preset)
    elif home:
        log.info(f"Firefly is updating the heating in {room} from {current} to {target}.")
        service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=target)
        service.call("climate", "set_preset_mode", entity_id=f"climate.{room}", preset_mode="home")
    else:
        log.info(f"Firefly is updating the heating in {room} from {current} to {pyscript.app_config["away_temperature"]} (currently set to away).")
        service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=pyscript.app_config["away_temperature"])
        service.call("climate", "set_preset_mode", entity_id=f"climate.{room}", preset_mode="away")


@service
def firefly_update_all_heating():
    log.info(f"Firefly is setting mode to '{"home" if is_home() else "away"}'.")
    [firefly_update_heating(room) for room in pyscript.app_config["rooms"]]


@state_trigger(f"{pyscript.app_config['zone']} or {pyscript.app_config['enabler']} or {pyscript.app_config['preheat']}")
def state_handler(trigger_type=None, var_name=None, value=None, old_value=None):
    if var_name == pyscript.app_config["zone"] and int(value) > 0 and int(old_value) > 0:
        return

    zone = int(state.get(pyscript.app_config['zone'])) > 0
    enable = state.get(pyscript.app_config['enabler']) == 'on'
    preheat = state.get(pyscript.app_config['preheat']) == 'on'

    if zone and enable and preheat:
        log.info("Firefly is turning pre-heat off.")
        service.call("input_boolean", "turn_off", entity_id=pyscript.app_config["preheat"])
    elif (zone and not enable and preheat) or (not zone and not enable and preheat):
        log.info("Firefly is turning enable on.")
        service.call("input_boolean", "turn_on", entity_id=pyscript.app_config["enabler"])
    else:
        firefly_update_all_heating()


@state_trigger(" or ".join([f"climate.{room}.temperature" for room in pyscript.app_config["rooms"]]))
def climate_handler(trigger_type=None, var_name=None, value=None, old_value=None):
    get_temp_target(var_name.split(".")[1])
