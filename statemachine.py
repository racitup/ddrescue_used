"""
Statemachine that allows other tasks to run in parallel.

Define States first, they can be purely symbolic or run a command once on entry.
Transitions are then added to the states and conditions must be mutually
exclusive since transitions are not ordered. The model spends all time in states
themselves and no time in transitions. So once an input event happens or
condition becomes True, actions are processed and then we enter the destination
state.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import time
import logging

# pylint: disable=too-few-public-methods
class State(object):
    """Definition of a state for use in the StateMachine.

    runonce is exec'd once on entry into the state.
    Don't forget you can create an iterable in runonce and call it using next()
    in the condition.
    """

    def __init__(self, name, runonce=None):
        if not isinstance(name, str):
            raise Exception('Name must be a string: {}'.format(name))
        self.name = name
        if runonce is not None and not isinstance(runonce, str):
            raise Exception("Runonce must be an exec'able string: {}"
                                .format(runonce))
        self.runonce = runonce
        self.tlist = []
    def __str__(self):
        return self.name
    def add_transition(self, dest, event=None, condition=None, actions=None):
        """dest - State instance. None signifies the end state and will exit.
        event - anything that will work as a dictionary key (hash & eq).
        condition - an eval'able string; event and condition cannot both be None
        actions - exec'able run on transition before entry to the dest state
        """
        if event is None and condition is None:
            raise Exception('Event and Condition cannot both be None!')
        transition = {'event':event}
        if condition is not None and not isinstance(condition, str):
            raise Exception("Condition must be None or an eval'able string: {}"
                                .format(condition))
        transition['condition'] = condition
        if actions is not None and not isinstance(actions, str):
            raise Exception("Actions must be None or an exec'able string: {}"
                                .format(actions))
        transition['actions'] = actions
        if dest is not None and not isinstance(dest, State):
            raise Exception('Dest must be None (end) or a State instance: {}'
                                .format(dest))
        transition['dest'] = dest
        self.tlist.append(transition)

class StateMachine(object):
    """State Machine.

    sleep_s - the sleep time in seconds between each machine loop
    start_state - the start State instance
    local, glob - define the context that the State code will run in
    """
    def __init__(self, sleep_s, start_state, local, glob):
        if not isinstance(start_state, State):
            raise Exception('Start state must be a State instance: {}'
                                .format(start_state))
        self.sleep_s = float(sleep_s)
        self.state = start_state
        self.eventdict = {}
        self.tasks = []
        self.current_task = None
        self.locals = local
        self.globals = glob
        return None

    def add_event(self, key, obj=None):
        """Add an event to the state machine queue.
        Can use the passed object in the state condition or action,
        the object will be called 'eventobj'
        """
        self.eventdict[key] = obj

    def add_persistent_task(self, task):
        """A task to run in-between state polls.
        Must be non-blocking, will be passed the state machine object as
        1st param for access to state, add_event() and remove_current_task()
        """
        if not callable(task):
            raise Exception('Task does not look callable {}'.format(task))
        self.tasks.append(task)

    def remove_current_task(self):
        """Allows a persistent task to remove itself from the list."""
        if self.current_task is not None:
            self.tasks.remove(self.current_task)

    # Since we have checked the types above,
    # we can safely convert None conditions to True and not execute None's
    def c_exec(self, exe):
        "Exec for the source context: locals & globals."
        if exe is None:
            return
        else:
            exec(exe, self.globals, self.locals)
    def c_eval(self, condition):
        "Eval for the source context: locals & globals."
        if condition is None:
            return True
        else:
            return eval(condition, self.globals, self.locals)

    def run(self):
        """State Machine main loop."""
        logging.info('Entering first state: {}'.format(self.state))
        self.c_exec(self.state.runonce)
        eventobj = None
        event_happened = False
        # Start transitions
        while self.state is not None:
            for transition in self.state.tlist:
        # transition: dest, event=None, condition=None, actions=None
                event = transition['event']
                if event_happened or event is None:
                    event_happened = True
                elif event in self.eventdict:
                    eventobj = self.eventdict.pop[event]
                    event_happened = True
                cond_result = self.c_eval(transition['condition'])
                logging.debug('{}: Event: {} is {}, Condition: {} is {}'
                                .format(self.state,
                                transition['event'], event_happened,
                                transition['condition'], cond_result))
                if event_happened and cond_result:
                    # We transition here - break out of for loop
                    self.c_exec(transition['actions'])
                    self.state = transition['dest']
                    eventobj = None
                    event_happened = False
                    logging.info('Entering state: {}'.format(self.state))
                    if self.state is not None:
                        self.c_exec(self.state.runonce)
                    break

            for task in self.tasks:
                self.current_task = task
                task(self)
            self.current_task = None
            time.sleep(self.sleep_s)

