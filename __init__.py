import datetime

TRIGGERS = {}

@time_trigger('startup')
def firefly():
    log.info("Firefly is starting up...")
    
    for room in [room for room in pyscript.app_config["rooms"]]:
        room_triggers = trigger_factory(room)

        TRIGGERS[room] = room_triggers

    log.info("Firefly is ready!")


def str_to_weekday(weekday):
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


def weekday_to_str(dow):
    return ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"][dow]


def get_cron(weekday, time):
    h, m = time.split(":")
    dow = str_to_weekday(weekday)

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
    weekday = weekday_to_str(dow)

    if weekday not in pyscript.app_config["rooms"][room] and weekday in ["saturday", "sunday"] and "weekend" in pyscript.app_config["rooms"][room]:
        weekday = "weekend"
    elif weekday not in pyscript.app_config["rooms"][room]:
        weekday = "default"
    
    current_schedule = get_current_schedule(room, weekday, timestamp)
    target = pyscript.app_config["rooms"][room][weekday][current_schedule]

    return target


def is_home():
    return [person for person in pyscript.app_config["tracking"] if state.get(person) == "home"] or state.get(pyscript.app_config["preheat"]) not in ["off, unavailable"]


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
            enabled_locks = [lock for lock in pyscript.app_config["locks"] if state.get(lock) not in ["off", "unavailable"]]
            enablers = [enabler for enabler in pyscript.app_config["enablers"] if state.get(enabler) not in ["off", "unavailable"]]
            temp = get_temp_target(room)

            if enabled_locks or not is_home() or not enablers:
                log.info(f"Firefly won't change the heating; locks: {enabled_locks} | Is home: {is_home}.")
                log.debug(f"{room} {temp}.")
                return
                    
            log.info(f"Firefly is updating the heating: {room} {temp}.")
            service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=temp)

        time_triggers.append(heat_change)

    return time_triggers


def reset_heating(room):
    temp = get_temp_target(room)
    current = state.getattr(f"climate.{room}")["temperature"]

    if temp == current:
        log.info(f"Firefly will keep the heating in {room} the same.")
    else:
        log.info(f"Firefly is resetting the heating in {room} to {temp}.")
        service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=temp)


@service
def firefly_reset_all_heating(enabler):
    for room in pyscript.app_config["rooms"]:
        reset_heating(room)

    service.call("input_boolean", "turn_on", entity_id=enabler)


def get_state_change_condition():
    enablers = " or ".join(pyscript.app_config["enablers"])
    locks = " or ".join(pyscript.app_config["locks"])
    tracking = " or ".join(pyscript.app_config["tracking"])
    preheat = pyscript.app_config["preheat"]

    return f"{enablers} or {locks} or {tracking} or {preheat}"


@state_trigger(get_state_change_condition())
def state_handler(trigger_type=None, var_name=None, value=None, old_value=None):
    home_count = len([person for person in pyscript.app_config["tracking"] if state.get(person) == "home"])

    if var_name in pyscript.app_config["tracking"] and old_value == "home" and home_count == 0:
        log.info("Firefly is setting the heating mode to 'away'.")

        for room in pyscript.app_config["rooms"]:
            service.call("climate", "set_preset_mode", entity_id=f"climate.{room}", preset_mode="away")

    elif (var_name in pyscript.app_config["tracking"] and old_value != "home" and home_count == 1) or var_name == pyscript.app_config["preheat"] and value not in ["off", "unavailable"]:
        log.debug("Firefly is setting the heating mode to 'home'.")

        for room in pyscript.app_config["rooms"]:
            service.call("climate", "set_preset_mode", entity_id=f"climate.{room}", preset_mode="home")

    elif var_name not in pyscript.app_config["tracking"] and var_name != pyscript.app_config["preheat"]:

        if not [enabler for enabler in pyscript.app_config["enablers"] if state.get(enabler) not in ["off", "unavailable"]]:
            log.info("Firefly can't see any enablers. Turning heating off.")
            for room in pyscript.app_config["rooms"]:
                service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=14)

        elif [lock for lock in pyscript.app_config["locks"] if state.get(lock) not in ["off", "unavailable"]]:
            log.info("Firefly is locked.")
            return

        else:
            log.info("Firefly is enabled and unlocked - resetting all rooms.")
            for room in pyscript.app_config["rooms"]:
                reset_heating(room)
