import json
import logging
import time
from urllib.parse import urljoin

import requests

from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject


class LimsClient(HardwareObject):
    """
    Client for the mx-lims-bff

    To simulate wrong loginID, use anything else than idtest
    To simulate wrong psd, use "wrong" for password
    To simulate ispybDown, but ldap login succeeds, use "ispybDown" for password
    To simulate no session scheduled, use "nosession" for password

    """

    def __init__(self, name: str):
        """
        Parameters
        ----------
        name : str
            Name of a Hardware object, e.g. `/lims`

        Returns
        -------
        None
        """
        HardwareObject.__init__(self, name)
        self.__translations = {}
        self.__disabled = False
        self.loginType = None
        self.base_result_url = None
        self.lims_rest = None
        self.REST = None

    def init(self) -> None:
        """
        Init method declared by HardwareObject.

        Returns
        -------
        None
        """
        self.lims_rest = self.get_object_by_role("lims_rest")
        self.authServerType = self.get_property("authServerType") or "ldap"
        if self.authServerType == "ldap":
            # Initialize ldap
            self.ldapConnection = self.get_object_by_role("ldapServer")
            if self.ldapConnection is None:
                logging.getLogger("HWR").debug("LDAP Server is not available")

        self.loginType = self.get_property("loginType") or "proposal"
        self.beamline_name = HWR.beamline.session.beamline_name

        self.REST = self.get_property("ws_root").strip()

        try:
            self.base_result_url = self.get_property("base_result_url").strip()
        except AttributeError:
            pass

    def get_login_type(self) -> str:
        """Gets the login type

        Returns
        -------
        str
            returns the login type
        """
        self.loginType = self.get_property("loginType") or "proposal"
        return self.loginType

    def login(
        self, loginID: str, psd: str, ldap_connection=None, create_session: bool = True
    ) -> dict:
        """Login method

        Parameters
        ----------
        loginID : str
            login ID
        psd : str
            passward
        ldap_connection : optional
            ldap connection, by default None
        create_session : bool, optional
            creates a new session, by default True

        Returns
        -------
        dict
            dictionary containing information about the status,
            proposal, session, local contact, person and laboratory
        """

        auth_url = f"{self.REST}/v1/authenticate"

        dict_data = {"user": loginID, "password": psd}
        data_json = json.dumps(dict_data)

        # Simulate authenticate endpoint?
        requests.post(auth_url, data=data_json)

        # simulate correct password
        if loginID != "idtest0":
            return {
                "status": {"code": "error", "msg": "loginID 'wrong' does not exist!"},
                "Proposal": None,
                "Session": None,
            }
        # to simulate wrong psd
        if psd == "wrong":
            return {
                "status": {"code": "error", "msg": "Wrong password!"},
                "Proposal": None,
                "Session": None,
            }

        # to simulate ispybDown, but login succeed
        if psd == "ispybDown":
            return {
                "status": {"code": "ispybDown", "msg": "ispyb is down"},
                "Proposal": None,
                "Session": None,
            }

        new_session = False
        if psd == "nosession":
            new_session = True
        prop = self.get_proposal(loginID, "")
        return {
            "status": {"code": "ok", "msg": "Successful login"},
            "Proposal": prop["Proposal"],
            "Session": {
                "session": prop["Session"],
                "new_session_flag": new_session,
                "is_inhouse": False,
            },
            "local_contact": "BL Scientist",
            "Person": prop["Person"],
            "Laboratory": prop["Laboratory"],
        }

    def get_todays_session(self, prop: dict) -> dict:
        """Gets todays session

        Parameters
        ----------
        prop : dict
            Proposal dictionary

        Returns
        -------
        dict
            dictionary containing todays session
        """
        try:
            sessions = prop["Session"]
        except KeyError:
            sessions = None
        # Check if there are sessions in the proposal
        todays_session = None
        if sessions is None or len(sessions) == 0:
            pass
        else:
            # Check for today's session
            for session in sessions:
                beamline = session["beamlineName"]
                start_date = "%s 00:00:00" % session["startDate"].split()[0]
                end_date = "%s 23:59:59" % session["endDate"].split()[0]
                try:
                    start_struct = time.strptime(start_date, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
                else:
                    try:
                        end_struct = time.strptime(end_date, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
                    else:
                        start_time = time.mktime(start_struct)
                        end_time = time.mktime(end_struct)
                        current_time = time.time()
                        # Check beamline name
                        if beamline == self.beamline_name:
                            # Check date
                            if current_time >= start_time and current_time <= end_time:
                                todays_session = session
                                break
        new_session_flag = False
        if todays_session is None:
            # a newSession will be created, UI (Qt, web) can decide to accept the
            # newSession or not
            new_session_flag = True
            current_time = time.localtime()
            start_time = time.strftime("%Y-%m-%d 00:00:00", current_time)
            end_time = time.mktime(current_time) + 60 * 60 * 24
            tomorrow = time.localtime(end_time)
            end_time = time.strftime("%Y-%m-%d 07:59:59", tomorrow)

            # Create a session
            new_session_dict = {}
            new_session_dict["proposalId"] = prop["Proposal"]["proposalId"]
            new_session_dict["startDate"] = start_time
            new_session_dict["endDate"] = end_time
            new_session_dict["beamlineName"] = self.beamline_name
            new_session_dict["scheduled"] = 0
            new_session_dict["nbShifts"] = 3
            new_session_dict["comments"] = "Session created by the BCM"
            self.create_session(new_session_dict)
            new_session_dict["sessionId"] = None

            todays_session = new_session_dict
            logging.getLogger("HWR").debug("create new session")

        else:
            session_id = todays_session["sessionId"]
            logging.getLogger("HWR").debug("getting local contact for %s" % session_id)
            self.get_session_local_contact(session_id)

        is_inhouse = HWR.beamline.session.is_inhouse(
            prop["Proposal"]["code"], prop["Proposal"]["number"]
        )
        return {
            "session": todays_session,
            "new_session_flag": new_session_flag,
            "is_inhouse": is_inhouse,
        }

    def echo(self) -> bool:
        """Returns true if the connection to the mx-lims-bff is successful

        Returns
        -------
        bool
            True if the connection is successful
        """
        response = requests.get(f"{self.REST}/v1/proposal/echo")
        logging.getLogger("HWR").debug(f"response.status_code: {response.status_code}")
        if response.status_code == 200:
            return True
        return False

    def get_proposal(self, proposal_code: str, proposal_number: int) -> dict:
        """
        Returns a dictionary containg Proposal, Person, Laboratory, Session and Status.
        Containing the data from the coresponding tables in the database
        the status of the database operations are returned in Status.

        Parameters
        ----------
        proposal_code : str
            The proposal code
        proposal_number : int
            The proposal number

        Returns
        -------
        dict
            A dictionary containing Proposal, Person, Laboratory, Sessions
            and Status.
        :rtype: dict
        """
        response = requests.get(f"{self.REST}/v1/proposal/get_proposal")
        return response.json()

    def get_proposals_by_user(self, user_name: str) -> list[dict]:
        """Gets proposal by user

        Parameters
        ----------
        user_name : str
            User name

        Returns
        -------
        list[dict]
            a list of proposals containing information about Proposal, Person,
            Laboratory, Sessions and Status.
        """
        response = requests.get(f"{self.REST}/v1/proposal/get_proposal")
        return [response.json()]

    def get_session_local_contact(self, session_id: int) -> dict:
        """Gets the session local contact

        Parameters
        ----------
        session_id : int
            The session id

        Returns
        -------
        dict
            A dictionary containing inforamtion about the Person
            running the experiment
        """
        response = requests.get(f"{self.REST}/v1/proposal/get_proposal")
        return response.json()["Person"]

    def translate(self, code, what):
        """
        TODO: Method not yet reviewed!!!

        Given a proposal code, returns the correct code to use in the GUI,
        or what to send to LDAP, user office database, or the ISPyB database.
        """
        try:
            translated = self.__translations[code][what]
        except KeyError:
            translated = code

        return translated

    def isInhouseUser(self, proposal_code: str, proposal_number: str) -> bool:
        """
        Returns True if the proposal is considered to be a
        in-house user.

        Parameters
        ----------
        proposal_code : str
            Proposal code
        proposal_number : str
            Proposal number

        Returns
        -------
        bool
            True if the proposal is considered to be an in-house user
        """
        for proposal in self["inhouse"]:
            if proposal_code == proposal.code:
                if str(proposal_number) == str(proposal.number):
                    return True
        return False

    def store_data_collection(self, mx_collection: dict, bl_config: dict = None):
        """
        TODO: Method not yet Implemented!!!

        Stores the data collection mx_collection, and the beamline setup
        if provided.

        Parameters
        ----------
        mx_collection : dict
            The data collection parameters.
        bl_config : dict
            The beamline setup.

        Returns
        -------
        None
        """
        logging.getLogger("HWR").debug(
            f"Data collection parameters stored: {str(mx_collection)}"
        )
        logging.getLogger("HWR").debug(f"Beamline setup stored: {str(bl_config)}")

        return None, None

    def store_beamline_setup(self, session_id, bl_config):
        """
        Stores the beamline setup dict <bl_config>.

        :param session_id: The session id that the bl_config
                           should be associated with.
        :type session_id: int

        :param bl_config: The dictonary with beamline settings.
        :type bl_config: dict

        :returns beamline_setup_id: The database id of the beamline setup.
        :rtype: str
        """

    def update_data_collection(self, mx_collection, wait=False):
        """
        Updates the datacollction mx_collection, this requires that the
        collectionId attribute is set and exists in the database.

        :param mx_collection: The dictionary with collections parameters.
        :type mx_collection: dict

        :returns: None
        """

    def update_bl_sample(self, bl_sample):
        """
        Creates or stos a BLSample entry.

        :param sample_dict: A dictonary with the properties for the entry.
        :type sample_dict: dict
        """

    def store_image(self, image_dict):
        """
        Stores the image (image parameters) <image_dict>

        :param image_dict: A dictonary with image pramaters.
        :type image_dict: dict

        :returns: None
        """

    def __find_sample(self, sample_ref_list, code=None, location=None):
        """
        Returns the sample with the matching "search criteria" <code> and/or
        <location> with-in the list sample_ref_list.

        The sample_ref object is defined in the head of the file.

        :param sample_ref_list: The list of sample_refs to search.
        :type sample_ref: list

        :param code: The vial datamatrix code (or bar code)
        :param type: str

        :param location: A tuple (<basket>, <vial>) to search for.
        :type location: tuple
        """

    def get_samples(self, proposal_id, session_id):
        response = requests.get(f"{self.REST}/v1/proposal/get_samples")
        return response.json()

    def get_session_samples(self, proposal_id, session_id, sample_refs):
        """
        Retrives the list of samples associated with the session <session_id>.
        The samples from ISPyB is cross checked with the ones that are
        currently in the sample changer.

        The datamatrix code read by the sample changer is used in case
        of conflict.

        :param proposal_id: ISPyB proposal id.
        :type proposal_id: int

        :param session_id: ISPyB session id to retreive samples for.
        :type session_id: int

        :param sample_refs: The list of samples currently in the
                            sample changer. As a list of sample_ref
                            objects
        :type sample_refs: list (of sample_ref objects).

        :returns: A list with sample_ref objects.
        :rtype: list
        """

    def get_bl_sample(self, bl_sample_id):
        """
        Fetch the BLSample entry with the id bl_sample_id

        :param bl_sample_id:
        :type bl_sample_id: int

        :returns: A BLSampleWSValue, defined in the wsdl.
        :rtype: BLSampleWSValue

        """

    def create_session(self, session_dict):
        pass

    def update_session(self, session_dict):
        pass

    def store_energy_scan(self, energyscan_dict):
        pass

    def associate_bl_sample_and_energy_scan(self, entry_dict):
        pass

    def get_data_collection(self, data_collection_id):
        """
        Retrives the data collection with id <data_collection_id>

        :param data_collection_id: Id of data collection.
        :type data_collection_id: int

        :rtype: dict
        """

    def get_data_collection_id(self, dc_dict):
        pass

    def dc_link(self, cid):
        """
        Get the LIMS link the data collection with id <id>.

        :param str did: Data collection ID
        :returns: The link to the data collection
        """
        dc_url = "ispyb/user/viewResults.do?reqCode=display&dataCollectionId=%s" % cid
        url = None
        if self.base_result_url is not None:
            url = urljoin(self.base_result_url, dc_url)
        return url

    def get_session(self, session_id):
        pass

    def store_xfe_spectrum(self, xfespectrum_dict):
        """
        Stores a xfe spectrum.

        :returns: A dictionary with the xfe spectrum id.
        :rtype: dict

        """

    def disable(self):
        self.__disabled = True

    def enable(self):
        self.__disabled = False

    def find_detector(self, type, manufacturer, model, mode):
        """
        Returns the Detector3VO object with the characteristics
        matching the ones given.
        """

    def store_data_collection_group(self, mx_collection):
        """
        Stores or updates a DataCollectionGroup object.
        The entry is updated of the group_id in the
        mx_collection dictionary is set to an exisitng
        DataCollectionGroup id.

        :param mx_collection: The dictionary of values to create the object from.
        :type mx_collection: dict

        :returns: DataCollectionGroup id
        :rtype: int
        """

    def _store_data_collection_group(self, group_data):
        pass

    def store_autoproc_program(self, autoproc_program_dict):
        pass

    def store_workflow(self, *args, **kwargs):
        return 1, 1, 1

    def _store_workflow(self, info_dict):
        pass

    def store_workflow_step(self, *args, **kwargs):
        return None

    def store_image_quality_indicators(self, image_dict):
        pass

    def set_image_quality_indicators_plot(self, collection_id, plot_path, csv_path):
        pass

    # Bindings to methods called from older bricks.
    getProposal = get_proposal
    getSessionLocalContact = get_session_local_contact
    createSession = create_session
    getSessionSamples = get_session_samples
    getSession = get_session
    storeDataCollection = store_data_collection
    storeBeamLineSetup = store_beamline_setup
    getDataCollection = get_data_collection
    updateBLSample = update_bl_sample
    getBLSample = get_bl_sample
    associateBLSampleAndEnergyScan = associate_bl_sample_and_energy_scan
    updateDataCollection = update_data_collection
    storeImage = store_image
    storeEnergyScan = store_energy_scan
    storeXfeSpectrum = store_xfe_spectrum

    def store_robot_action(self, robot_action_dict):
        """Stores robot action"""
