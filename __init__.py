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
        if get_timestamp(h, m) < current_timestamp:
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
        if day == "default": # fill empty days
            for weekday in [weekday for weekday in weekdays if not weekdays[weekday]]:
                weekdays[weekday] = create_triggers(room, day, weekday)
        elif day == "weekend": # fill sat + sun if empty
            for weekday in [weekday for weekday in weekdays if weekday in ["saturday", "sunday"]]:
                weekdays[weekday] = create_triggers(room, day, weekday)
        elif day in weekdays.keys(): # fill in day
            weekdays[weekday] = create_triggers(room, day, day)

    return weekdays


def create_triggers(room, day, weekday):
    time_triggers = []

    for time in [time for time in pyscript.app_config["rooms"][room][day]]:
        temp = pyscript.app_config["rooms"][room][day][time]
        log.debug(f"Firefly is creating a trigger in {room} for {weekday} at {time} and temp {temp}")

        @time_trigger(get_cron(weekday, time))
        def heat_change():
            enabled_locks = [lock for lock in pyscript.app_config["locks"] if state.get(lock) not in ["off", "unavailable"]]
            if enabled_locks or not is_home():
                log.info(f"Firefly won't change the heating; locks: {enabled_locks} | Is home: {is_home}.")
                log.debug(f"{room} {weekday} {time} {temp}.")
                return
                    
            log.info(f"Firefly is updating the heating: {room} {weekday} {time} {temp}.")
            service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=temp)

        time_triggers.append(heat_change)

    return time_triggers


@service
def reset_heating(room):
    temp = get_temp_target(room)

    log.info(f"Firefly is resetting the heating in {room} to {temp}.")

    service.call("climate", "set_temperature", entity_id=f"climate.{room}", temperature=temp)


def get_locks_condition():
    return " in ['off', 'unavailable'] and ".join(pyscript.app_config["locks"]) + " in ['off', 'unavailable']" if pyscript.app_config["locks"] else "1 == 2"


def get_preheat_condition():
    return f"{pyscript.app_config['preheat']} == 'on'"


def get_person_home_condition():
    return " == 'home' or ".join(pyscript.app_config["tracking"]) + " == 'home'"
    

@state_trigger(get_locks_condition())
def tpp_reset_heating_unlocked(room = None):
    if not is_home():
        return
    
    reset_heating(room) if room else [reset_heating(r) for r in pyscript.app_config["rooms"]]


@state_trigger(get_preheat_condition())
def tpp_reset_heating_preheat(room = None):
    if [lock for lock in pyscript.app_config["locks"] if state.get(lock) not in ["off", "unavailable"]]:
        return

    if [person for person in pyscript.app_config["tracking"] if state.get(person) == "home"]:
        service.call("input_boolean", "turn_off", entity_id=pyscript.app_config['preheat'])
        return

    reset_heating(room) if room else [reset_heating(r) for r in pyscript.app_config["rooms"]]


@state_trigger(get_person_home_condition())
def person_home(room = None):
    if [lock for lock in pyscript.app_config["locks"] if state.get(lock) not in ["off", "unavailable"]]:
        return

    if len([person for person in pyscript.app_config["tracking"] if state.get(person) == "home"]) != 1:
        return

    service.call("input_boolean", "turn_off", entity_id=pyscript.app_config['preheat'])

    reset_heating(room) if room else [reset_heating(r) for r in pyscript.app_config["rooms"]]
