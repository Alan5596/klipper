#!/usr/bin/env python
# Main code for host side printer firmware
#
# Copyright (C) 2016  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import sys, optparse, ConfigParser, logging, time, threading
import gcode, toolhead, util, mcu, fan, heater, extruder, reactor, queuelogger

class ConfigWrapper:
    def __init__(self, printer, section):
        self.printer = printer
        self.section = section
    def get(self, option, default=None):
        if not self.printer.fileconfig.has_option(self.section, option):
            return default
        return self.printer.fileconfig.get(self.section, option)
    def getint(self, option, default=None):
        if not self.printer.fileconfig.has_option(self.section, option):
            return default
        return self.printer.fileconfig.getint(self.section, option)
    def getfloat(self, option, default=None):
        if not self.printer.fileconfig.has_option(self.section, option):
            return default
        return self.printer.fileconfig.getfloat(self.section, option)
    def getboolean(self, option, default=None):
        if not self.printer.fileconfig.has_option(self.section, option):
            return default
        return self.printer.fileconfig.getboolean(self.section, option)
    def getsection(self, section):
        return ConfigWrapper(self.printer, section)

class Printer:
    def __init__(self, conffile, debuginput=None):
        self.fileconfig = ConfigParser.RawConfigParser()
        self.fileconfig.read(conffile)
        self.reactor = reactor.Reactor()

        self._pconfig = ConfigWrapper(self, 'printer')
        ptty = self._pconfig.get('pseudo_tty', '/tmp/printer')
        if debuginput is None:
            pseudo_tty = util.create_pty(ptty)
        else:
            pseudo_tty = debuginput.fileno()

        self.gcode = gcode.GCodeParser(
            self, pseudo_tty, inputfile=debuginput is not None)
        self.mcu = mcu.MCU(self, ConfigWrapper(self, 'mcu'))
        self.stats_timer = self.reactor.register_timer(
            self.stats, self.reactor.NOW)
        self.connect_timer = self.reactor.register_timer(
            self.connect, self.reactor.NOW)

        self.objects = {}
        if self.fileconfig.has_section('fan'):
            self.objects['fan'] = fan.PrinterFan(
                self, ConfigWrapper(self, 'fan'))
        if self.fileconfig.has_section('extruder'):
            self.objects['extruder'] = extruder.PrinterExtruder(
                self, ConfigWrapper(self, 'extruder'))
        if self.fileconfig.has_section('heater_bed'):
            self.objects['heater_bed'] = heater.PrinterHeater(
                self, ConfigWrapper(self, 'heater_bed'))
        self.objects['toolhead'] = toolhead.ToolHead(
            self, self._pconfig)

    def stats(self, eventtime):
        out = []
        out.append(self.gcode.stats(eventtime))
        out.append(self.objects['toolhead'].stats(eventtime))
        out.append(self.mcu.stats(eventtime))
        logging.info("Stats %.0f: %s" % (eventtime, ' '.join(out)))
        return eventtime + 1.
    def build_config(self):
        for oname in sorted(self.objects.keys()):
            self.objects[oname].build_config()
        self.gcode.build_config()
        self.mcu.build_config()
    def connect(self, eventtime):
        self.mcu.connect()
        self.build_config()
        self.gcode.run()
        self.reactor.unregister_timer(self.connect_timer)
        return self.reactor.NEVER
    def connect_file(self, output, dictionary):
        self.reactor.update_timer(self.stats_timer, self.reactor.NEVER)
        self.mcu.connect_file(output, dictionary)
    def run(self):
        self.reactor.run()
        # If gcode exits, then exit the MCU
        self.stats(time.time())
        self.mcu.disconnect()
        self.stats(time.time())
    def shutdown(self):
        self.gcode.shutdown()


######################################################################
# Startup
######################################################################

def read_dictionary(filename):
    dfile = open(filename, 'rb')
    dictionary = dfile.read()
    dfile.close()
    return dictionary

def main():
    usage = "%prog [options] <config file>"
    opts = optparse.OptionParser(usage)
    opts.add_option("-o", "--debugoutput", dest="outputfile",
                    help="write output to file instead of to serial port")
    opts.add_option("-i", "--debuginput", dest="inputfile",
                    help="read commands from file instead of from tty port")
    opts.add_option("-l", "--logfile", dest="logfile",
                    help="write log to file instead of stderr")
    opts.add_option("-v", action="store_true", dest="verbose",
                    help="enable debug messages")
    opts.add_option("-d", dest="read_dictionary",
                    help="file to read for mcu protocol dictionary")
    options, args = opts.parse_args()
    if len(args) != 1:
        opts.error("Incorrect number of arguments")
    conffile = args[0]

    debuginput = debugoutput = bglogger = None

    debuglevel = logging.INFO
    if options.verbose:
        debuglevel = logging.DEBUG
    if options.inputfile:
        debuginput = open(options.inputfile, 'rb')
    if options.outputfile:
        debugoutput = open(options.outputfile, 'wb')
    if options.logfile:
        bglogger = queuelogger.setup_bg_logging(options.logfile, debuglevel)
    else:
        logging.basicConfig(level=debuglevel)
    logging.info("Starting Klippy...")

    # Start firmware
    printer = Printer(conffile, debuginput=debuginput)
    if debugoutput:
        proto_dict = read_dictionary(options.read_dictionary)
        printer.connect_file(debugoutput, proto_dict)
    printer.run()

    if bglogger is not None:
        bglogger.stop()

if __name__ == '__main__':
    main()