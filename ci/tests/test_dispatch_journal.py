"""Compile and exercise dispatch durability and the unsupported Windows branch."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class JournalTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++') and shutil.which('pkg-config'), 'host C++/Qt tools required')
    def test_deposit_replay_and_windows_refusal(self):
        probe = subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt6Core'], capture_output=True, text=True)
        if probe.returncode:
            self.skipTest('host Qt6Core development package required')
        qt = ROOT / 'src/qt'
        header = qt / 'workdepositjournal.h'
        includes = '\n'.join(line for line in header.read_text().splitlines()
                             if line.startswith('#include') and not any(x in line for x in ('unistd', 'fcntl', 'sys/stat')))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for windows in (False, True):
                directory = root / ('windows' if windows else 'unix')
                if not windows:
                    directory.mkdir(mode=0o700)
                source = includes + '\n#include <QCoreApplication>\n'
                if windows:
                    source += '#define Q_OS_WIN\n'
                source += '#include "workdepositjournal.h"\n'
                source += 'int main(int argc,char** argv){QCoreApplication app(argc,argv);QString d=QString::fromLocal8Bit(argv[1]);'
                if windows:
                    source += 'try{WorkDepositJournal j(d);return 1;}catch(const std::runtime_error&){return QDir(d).exists()?2:0;}}'
                else:
                    source += '''WorkDepositJournal j(d);WorkFunding::Review r;
                    r.quoteId=QString(32,'a');r.digest=QString(64,'b');r.receivingScript="76a914"+QString(40,'c')+"88ac";r.amount=1000;
                    QString tx(64,'d');j.begin(r,tx,0);
                    try{j.begin(r,tx,0);return 1;}catch(const std::runtime_error&){}
                    j.submitted(r.quoteId,tx);return j.status(r.quoteId)["state"]=="submitted"?0:2;}'''
                cpp = root / 'probe.cpp'; cpp.write_text(source)
                binary = root / 'probe'
                subprocess.run(['c++', '-std=c++17', '-fPIC', '-I'+str(qt), str(cpp), '-o', str(binary), *probe.stdout.split()], check=True, capture_output=True)
                subprocess.run([str(binary), str(directory)], check=True)

    @unittest.skipUnless(shutil.which('c++') and shutil.which('pkg-config'), 'host C++/Qt tools required')
    def test_durable_reuse_and_windows_refusal(self):
        probe = subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt6Core'], capture_output=True, text=True)
        if probe.returncode:
            self.skipTest('host Qt6Core development package required')
        header = ROOT / 'src/qt/workdispatchjournal.h'
        # Preload Qt before selecting the branch, without pretending the host
        # Qt installation itself is Windows. Real MinGW compilation runs in CI.
        includes = '\n'.join(line for line in header.read_text().splitlines()
                             if line.startswith('#include') and 'unistd' not in line and 'fcntl' not in line)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for windows in (False, True):
                directory = root / ('windows' if windows else 'unix')
                source = includes + '\n#include <QCoreApplication>\n'
                if windows:
                    source += '#define Q_OS_WIN\n'
                source += '#include "' + str(header) + '"\n'
                source += 'int main(int argc,char** argv){QCoreApplication app(argc,argv);QString d=QString::fromLocal8Bit(argv[1]);QJsonObject b{{"order","one"}};'
                if windows:
                    source += 'try{WorkDispatch::intent(d,b);return 1;}catch(const std::runtime_error&){return QDir(d).exists()?2:0;}}'
                else:
                    source += 'auto a=WorkDispatch::intent(d,b);if(a!=WorkDispatch::intent(d,b))return 1;if(a==WorkDispatch::intent(d,QJsonObject{{"order","two"}}))return 2;return 0;}'
                cpp = root / 'probe.cpp'; cpp.write_text(source)
                binary = root / 'probe'
                subprocess.run(['c++', '-std=c++17', '-fPIC', str(cpp), '-o', str(binary), *probe.stdout.split()], check=True, capture_output=True)
                subprocess.run([str(binary), str(directory)], check=True)


if __name__ == '__main__':
    unittest.main()
