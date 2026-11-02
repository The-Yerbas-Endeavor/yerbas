QT += widgets testlib network
CONFIG += c++17 console testcase
CONFIG -= app_bundle
TARGET = page_test
INCLUDEPATH += ../../../../src/qt
SOURCES += page_test.cpp ../../../../src/qt/yerbasaipage.cpp
HEADERS += ../../../../src/qt/yerbasaipage.h ../../../../src/qt/rewarddisplay.h ../../../../src/qt/requestdisplay.h
