import Microdiff
import gevent
import sample_centring


class MD3UP(Microdiff.Microdiff):
    def __init__(self, *args, **kwargs):
        Microdiff.Microdiff.__init__(self, *args, **kwargs) 
       
    def init(self):
        Microdiff.Microdiff.init(self)
 
        self.centringPhi=sample_centring.CentringMotor(self.phiMotor, direction=1)
        # centringPhiz => should be renamed centringVertical
        self.centringPhiz=sample_centring.CentringMotor(self.phizMotor)
        # centringPhiy => should be renamed centringHorizontal
        self.centringPhiy=sample_centring.CentringMotor(self.phiyMotor, direction=-1, reference_position=0.0037)
        self.centringSamplex=sample_centring.CentringMotor(self.sampleXMotor, direction=-1)
        self.centringSampley=sample_centring.CentringMotor(self.sampleYMotor)

    def getBeamPosX(self):
        return self.beam_info.get_beam_position()[0]

    def getBeamPosY(self):
        return self.beam_info.get_beam_position()[1]

