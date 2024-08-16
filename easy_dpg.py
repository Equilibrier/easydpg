import dataclasses

from typing import Union, Literal, List, Tuple, Dict, Callable, Any
import os
import re
import random

#import faulthandler
#faulthandler.enable()

from dearpygui import dearpygui as dpg

from .dpg_utils import error_or_info_box, create_progressbar_theme, create_button_theme, create_window_theme, create_child_window_theme, rgb256_to_hsv01, _batch_map_01_to_256
from .generic_utils import extract_int_scalar
from .redux import ReduxStore, ReduxState
from .dpg_utils import get_fullscreen_dimensions

##################################################
# CUSTOM TYPES

#EasyDPGWrapper...
RegisterElementFunc = Callable[[Union[str, int], str], None]
BuilderCallback = Callable[['EasyDPGWidget', RegisterElementFunc], None]
ElementsRegistry = Dict[str, 'EasyDPGWrapper']
WidgetReduxListener = Callable[['EasyDPGWidget', ElementsRegistry, str, ReduxState], None]
DPGParent = Union[int, str, None]
AnyParent = Union[int, str, 'EasyDPGWrapper', None]

#EasyDPGApp
MouseMoveListener = Callable[[int, int], None]
MousePressedButton = Literal['r', 'l', 'm']
MousePressListener = Callable[[MousePressedButton], None]
KeyboardPressedScancode = int # @TODO nu am testat ce-mi vine prin callback dpg, de fapt...
KeyboardPressedKey = str # @TODO nu am testat ce-mi vine prin callback dpg, de fapt...
KeyboardPressListener = Callable[[KeyboardPressedScancode, KeyboardPressedKey], None]
RenderListener = Callable[[],None]

# LM-uri (Layout Manageri)
LMRecalculateResult = Dict[Union[str, int], Dict[str, int]] # un dict cu tag-urile descendetilor unui LM, cu pos_x, pos_y, width si height al spatiului virtual alocat pentru fiecare
LMProportionalAdjusterResultRowProvider = Callable[[int, int, int], Dict[str, int]]

# Wrapper aids
UniversalColor = Union[float, int, List[int], List[float]]
ThemeCreator = Callable[[UniversalColor], str]
##########################

############################################################
# USEFUL OOP CONSTRUCTS
##############################
_CONTEXT_MANAGEABLE_DPG_ITEMS = ["mvgroup", "mvwindowappitem", "mvchildwindow"] #,TODO...]
_VISIBILITY_DPG_ITEMS = ["mvprogressbar", "mvbutton", "mvfiledialog", "mvtext", "mvcheckbox", "mvgroup", "mvwindowappitem", "mvchildwindow", "mvspacer", "mvinputtext", "mvinputfloat", "mvinputint", "mvinputintmulti", "mvinputfloatmulti", "mvinputdouble", "mvinputDoublemulti"] #,TODO...]
_GEOMETRY_SIZE_MANAGEABLE_DPG_ITEMS = ["mvprogressbar", "mvbutton", "mvfiledialog", "mvgroup", "mvwindowappitem", "mvchildwindow", "mvspacer", "mvinputtext", "mvinputfloat", "mvinputint", "mvinputintmulti", "mvinputfloatmulti", "mvinputdouble", "mvinputDoublemulti"] #,TODO...] # @TODO nu toate elementele au si marimea gestionabila, de ex mvtext, dar au macar pozitia gestionabila (toate) si cum gestionarul se ocupa de geometrie, in general, nu stiu cum sa gestionez treaba asta, deocamdata o las asa, intra si vaca si portcul si toate, dar unele metode vor genera exceptii si apelantul trebuie sa fie atent la asta:  "mvtext" mvtext NU are width & height
_DEFCALLBACK_DPG_ITEMS = ["mvbutton", "mvfiledialog", "mvcheckbox"] #,TODO...]
_BACKGCOLOR_DPG_ITEMS = ["mvprogressbar", "mvbutton", "mvwindowappitem", "mvchildwindow", "mvinputtext", "mvinputfloat", "mvinputint", "mvinputintmulti", "mvinputfloatmulti", "mvinputdouble", "mvinputDoublemulti"] #,TODO...]
_SINGLEVALUE_DPG_ITEMS = ["mvcheckbox", "mvtext", "mvprogressbar"]

def _get_simplified_type(tag): return dpg.get_item_type(tag).split("::")[1].strip().lower()
def _guard_incompatible_type(tag, compatible_types, exception_msg=lambda tag, item_type, compatible_types: f"wrong tag id {tag} (of type '{item_type}'), expected a tag from one of the following types:\n\t{compatible_types}"):
    type_ = _get_simplified_type(tag)
    if type_ not in compatible_types:
        raise Exception(exception_msg(tag, type_, compatible_types))

from .generic_utils import guard_class_against_non_di_instantiation

class _EasyDPGWrapperColor:
    def __init__(self, tag, theme_creator:ThemeCreator = lambda color_hue_or_rgb_and_or_alpha: dpg.add_theme()):
        self.tag_ = tag
        self.theme_creator_ = theme_creator
        _guard_incompatible_type(tag, _BACKGCOLOR_DPG_ITEMS)

    def set_background_color(self, background_color_hue_or_rgb_and_or_alpha: UniversalColor = None):
        #print(f"set-color({self}): lambda: {self.theme_creator_}")
        self.__apply_background_color_if_valid(element_tag=self.tag_, background_color_hue_or_rgb_and_or_alpha=background_color_hue_or_rgb_and_or_alpha); return self

    def __apply_background_color_if_valid(self, element_tag, background_color_hue_or_rgb_and_or_alpha: UniversalColor = None):
        if background_color_hue_or_rgb_and_or_alpha is not None:
            old_theme = dpg.get_item_theme(element_tag)
            if old_theme is not None:
                dpg.delete_item(old_theme)

            new_theme_ = self.theme_creator_(background_color_hue_or_rgb_and_or_alpha)
            dpg.bind_item_theme(element_tag, new_theme_)

@dataclasses.dataclass
class EasyDPGAppConfigurator:
    background_color: UniversalColor
    pos: Union[Tuple[int, int], None]
    size: Union[Tuple[Union[str, int], Union[str, int]], None]
    fullscreen: bool

def _configure_app(binder):
    configuration = EasyDPGAppConfigurator(background_color=globals()['_APP_BACKGROUND_COLOR'], pos=globals()['_APP_POS'], size=globals()['_APP_SIZE'], fullscreen=globals()['_APP_FULLSCREEN'])
    binder.bind(EasyDPGAppConfigurator, to=configuration, scope=singleton) # poate fi singleton sau ne-singleton (instance) ca nici nu conteaza, fiindca oricum va fi folosita o singura data, pentru o singura clasa (care e ea insasi un singleton)...

class EasyDPGApp:
    def __init__(self, configurator: EasyDPGAppConfigurator): # background_color is hue_or_rgb_and_or_alpha
        guard_class_against_non_di_instantiation()

        self.configurator_ = configurator

        self.running_ = False
        self.mouse_position_listeners_: Dict[str, MouseMoveListener] = {}
        self.mouse_press_listeners_: Dict[str, MousePressListener] = {}
        self.keyboard_press_listeners_: Dict[str, KeyboardPressListener] = {}
        self.key_map_ = { # @TODO NETESTATE prea mult, determinate experimental, verificare sporadic, unde a fost nevoie - lista supusa corectarii si TODO inca nu stiu daca astea sunt scancode-urile de la tastatura fizica, sau codurile interpretate de OS (daca sunt probleme de inconsistenta, mai bine aflu tastele cu alta biblioteca) (totusi, fiindca literele sunt aceleasi cu codul ascii, pp ca OS-ul le da asa, deci ca ar fi interpretate -- luam pp cu sare, ca testul cu ro/en z-y nu mi-a iesit, mereu y e 89 si z e 90)
            257: "enter",
            256: "escape",
            344: "rshift",
            340: "lshift",
            346: "ralt", # lalt (left-alt) e preluat, probabil, de OS, nu il primesc de la dpg de nici o culoare :)...
            341: "rctrl",
            345: "lctrl",
            32: "space",
            259: "backspace",
            260: "insert",
            268: "home",
            266: "pageup",
            261: "delete",
            269: "end",
            267: "pagedown",
            281: "scrolllock",
            284: "pausebreak", # print-scr mi-e capturat de OS, nu pot sa-l prind, oricum nu trebuie :D (tocmai fiindca e capturat de OS si nu-l poti folosi, daaahh ! :) )...
            265: "arrowup",
            264: "arrowdown",
            263: "arrowleft",
            262: "arrowright",
            348: "contextualmenu",
            347: "window",
            280: "capslock",
            258: "tab",
            290: "f1",
            291: "f2",
            292: "f3",
            293: "f4",
            294: "f5",
            295: "f6",
            296: "f7",
            297: "f8",
            298: "f9",
            299: "f10",
            300: "f11",
            301: "f12",
            96: "`~",
            48: "0)",
            49: "1!",
            50: "2@",
            51: "3#",
            52: "4$",
            53: "5%",
            54: "6^",
            55: "7&",
            56: "8*",
            57: "9(",
            45: "-_",
            61: "=+",
            91: "[{",
            93: "]}",
            92: "\\|",
            59: ";:",
            39: "'\"",
            44: ",<",
            46: ".>",
            47: "/?",
            320: "numpad0",
            321: "numpad1",
            322: "numpad2",
            323: "numpad3",
            324: "numpad4",
            325: "numpad5",
            326: "numpad6",
            327: "numpad7",
            328: "numpad8",
            329: "numpad9",
            282: "numlock",
            331: "numpad/",
            332: "numpad*",
            333: "numpad-",
            334: "numpad+",
            335: "numpadenter",
            330: "numpaddelete"
        }
        for k in range(65, 90 + 1): # la litere e simplu, sunt aceleasi cu codul ascii
            self.key_map_[k] = chr(k).lower()

        self.pre_render_listeners_ = {}
        self.post_render_listeners_ = {}

        self.root_tag_ = None

        self.updated_viewport_width_ = None
        self.updated_viewport_height_ = None

        self.widgets_store_: Dict[str, 'EasyDPGWidget'] = {}

    def _auto_register_widget(self, widget, name):
        self.widgets_store_[name] = widget

    def lookup_widget(self, name) -> Union['EasyDPGWidget', None]: return self.widgets_store_[name] if name in self.widgets_store_ else None

    def __generate_listener_id_(self, prefix="listener"):
        return f"{prefix}_{int(random.random() * 1000000)}"

    def register_mouse_move_listener(self, listener: MouseMoveListener):
        id_ = self.__generate_listener_id_("mml")
        self.mouse_position_listeners_[id_] = listener
        return lambda: self.mouse_position_listeners_.pop(id_)

    def register_mouse_press_listener(self, listener: MousePressListener):
        id_ = self.__generate_listener_id_("mpl")
        self.mouse_press_listeners_[id_] = listener
        return lambda: self.mouse_press_listeners_.pop(id_)

    def register_keyboard_press_listener(self, listener: KeyboardPressListener):
        id_ = self.__generate_listener_id_("kpl")
        self.keyboard_press_listeners_[id_] = listener
        return lambda: self.keyboard_press_listeners_.pop(id_)

    def register_pre_render_listener(self, listener: RenderListener = lambda: print("WARNING: EasyDPGApp: register_pre_render_listener: NOP listener for dpg renders, this SHOULD BE REPLACED with a valid implementation, instead !")):
        #print(f"@@@@@@@@@@@@@ register_pre_render_listener la timpul {time.time()}")
        id_ = self.__generate_listener_id_("prl")
        self.pre_render_listeners_[id_] = listener
        return lambda: self.pre_render_listeners_.pop(id_)
    def register_post_render_listener(self, listener: RenderListener = lambda: print("WARNING: EasyDPGApp: register_post_render_listener: NOP listener for dpg renders, this SHOULD BE REPLACED with a valid implementation, instead !")):
        #print(f"@@@@@@@@@@@@@ register_post_render_listener la timpul {time.time()}")
        id_ = self.__generate_listener_id_("psrl")
        self.post_render_listeners_[id_] = listener
        return lambda: self.post_render_listeners_.pop(id_)


    def __dispatch_pre_render_event(self):
        listeners_ = list(self.pre_render_listeners_.values()) # pentru daca apelezi register_<blah>_listener during calback, otherwise it will throw a "RuntimeError: dictionary changed size during iteration"
        for l in listeners_:
            l()

    def __dispatch_post_render_event(self):
        #print(f"@@@@@@@@@@@@@ __dispatch_post_render_event la timpul {time.time()}")
        listeners_ = list(self.post_render_listeners_.values())
        for l in listeners_:
            l()
    def __dispatch_mouse_move(self, x, y):
        listeners_ = list(self.mouse_position_listeners_.values())
        for l in listeners_:
            l(x, y)
    def __dispatch_mouse_press(self, pressed_button: MousePressedButton):
        listeners_ = list(self.mouse_press_listeners_.values())
        for l in listeners_:
            l(pressed_button)
    def __dispatch_keyboard_press(self, pressed_scancode: KeyboardPressedScancode):
        if pressed_scancode == 342: # nu stiu de ce mereu tot genereaza tasta asta, dupa orice alta tasta...
            #print(342) # cu asta @TODO pot detecta secvente, desi si combinatii de taste, daca de ex detectez ca in secventa e o tasta extinsa (sau mai multe) o pot considera combinatie sau mai multe combinatii cu acea tasta extinsa, altfel doar o apasare succesiva la timp scurt, deci o pot desparti in taste individuale -- dar nu stiu daca se merita, odata ca la dpg nu-mi trebuie chestii poate atat de avansate (desi combinatiile, ca scurtaturi de la tastatura ba) si nu cumva e mai bine sa oflosesc atatea alte pachete de detectare evenimente tastatura, care deja fac logica de genul in spate
            return
        #print(self.key_map_[pressed_scancode])

        listeners_ = list(self.keyboard_press_listeners_.values())
        for l in listeners_:
            l(pressed_scancode, self.key_map_[pressed_scancode])

    def __viewport_resized(self):
        self.updated_viewport_width_ = dpg.get_viewport_client_width()
        self.updated_viewport_height_ = dpg.get_viewport_client_height()

    def start(self, create_ui: Callable=lambda: None):
        if not self.running_:
            self.running_ = True
            dpg.create_context()
            self._install_controller_listeners()
            with EasyDPGWrapperPrimaryPanel.build(background_color_hue_or_rgb_and_or_alpha=self.configurator_.background_color) as w:
                #w.set_movable() # just for DEBUGGING purposes...
                #w.set_resizable()
                self.root_tag_ = w.tag()
                create_ui()

            fs_width_, fs_height_ = get_fullscreen_dimensions()
            size = [None, None]
            if self.configurator_.size is None:
                size = [fs_width_, fs_height_]
            size[0] = int(self.configurator_.size[0]) if type(self.configurator_.size[0]) is int or (type(self.configurator_.size[0]) is float and self.configurator_.size[0] > 1.0) else (float(int(self.configurator_.size[0].strip()[:-1]) / 100.0) if type(self.configurator_.size[0]) is str and '%' in self.configurator_.size[0] else (self.configurator_.size[0] if type(self.configurator_.size[0]) is float else None))
            if size[0] is None:
                raise Exception(f"EasyDPGApp: invalid size[0] (width) given: {size[0]}. Should be [0,1] float, or an absolute integer or a % specified percentage (as str) !")
            size[1] = int(self.configurator_.size[1]) if type(self.configurator_.size[1]) is int or (type(self.configurator_.size[1]) is float and self.configurator_.size[1] > 1.0) else (float(int(self.configurator_.size[1].strip()[:-1]) / 100.0) if type(self.configurator_.size[1]) is str and '%' in self.configurator_.size[1] else (self.configurator_.size[1] if type(self.configurator_.size[1]) is float else None))
            if size[1] is None:
                raise Exception(f"EasyDPGApp: invalid size[1] (height) given: {size[1]}. Should be [0,1] float, or an absolute integer or a % specified percentage (as str) !")
            
            size[0] = self.configurator_.size[0] if type(self.configurator_.size[0]) is int else int(fs_width_ * size[0])
            size[1] = self.configurator_.size[1] if type(self.configurator_.size[1]) is int else int(fs_height_ * size[1])

            size = tuple(size)            
            pos = self.configurator_.pos if self.configurator_.pos is not None else (int((fs_width_ - size[0]) / 2), int((fs_height_ - size[1]) / 2))

            dpg.create_viewport(decorated=not(self.configurator_.fullscreen is not None and self.configurator_.fullscreen), always_on_top=self.configurator_.fullscreen is not None and self.configurator_.fullscreen, y_pos=pos[1], x_pos=pos[0], width=size[0], height=size[1])
            #dpg.create_viewport(y_pos=pos[1], x_pos=pos[0])
            dpg.setup_dearpygui()

            # @TODO se poate face un switch la constructor prin care sa poti activa chestii de depanare (si poate sa obligi cumva fereastra principala sa fie 'mutabila' ca altfel nu te poti uita la panourile astea de depanare...
            #dpg.show_item_registry() # for DEBUGGING purposes

            dpg.set_viewport_resize_callback(callback=self.__viewport_resized)

            dpg.show_viewport()
            while self.running_ and dpg.is_dearpygui_running():
                self.__dispatch_pre_render_event() # @TODO nu ar strica astea doua dispatch-uri sa fie executate in fir de executie separat, de fapt asa s-ar cere, ca firul de randare (iata, si calcule) UI, sa se intample cat mai 'la sigur', neimpiedicat de nimeni...
                self.render_frame()
                self.__dispatch_post_render_event()
                if self.updated_viewport_width_ is not None:# or self.updated_viewport_height_ is not None:
                    EasyDPGWrapperPrimaryPanel(self.root_tag_).set_width(self.updated_viewport_width_)
                    EasyDPGWrapperPrimaryPanel(self.root_tag_).set_height(self.updated_viewport_height_)
                    self.updated_viewport_width_ = None
                    self.updated_viewport_height_ = None

            dpg.destroy_context()

    def render_frame(self): dpg.render_dearpygui_frame()

    def root_tag(self): return self.root_tag_

    def _install_controller_listeners(self):
        # Assuming dpg functions to attach these handlers
        with dpg.handler_registry():
            dpg.add_mouse_move_handler(callback=lambda sender, app_data: self.__dispatch_mouse_move(app_data[0], app_data[1]))
            dpg.add_mouse_click_handler(callback=lambda sender, app_data: self.__dispatch_mouse_press("l" if app_data == 0 else ("r" if app_data == 1 else "m")))
            dpg.add_key_release_handler(callback=lambda sender, app_data: self.__dispatch_keyboard_press(app_data))

    def stop(self):
        self.running_ = False


class _LayoutManagerController:

    def __init__(self):
        self.app_: EasyDPGApp = FACTORY(EasyDPGApp)
        self.app_.register_pre_render_listener(self.__do_pre_render_operations)
        self.app_.register_post_render_listener(self.__do_post_render_operations)

        self.entry_index_ = None
        self.exit_index_ = None
        self.dfs_nodes_depth_ = None
        self.dfs_nodes_children_count_: Dict[Union[str, int], int] = None
        self.lms_: Dict[Union[str, int], Dict[str, Any]] = {}
        self.resized_lms_: Dict[Union[str, int], bool] = {}

        self.first_postrender_run_ = True

    def is_lm_registered(self, tag): return tag in self.lms_.keys()

    def _register_lm(self, lm_instance: '_EasyDPGLayoutManagerBase'):
        print(f'inregistrez lm _EasyDPGLayoutManagerBase cu tag {lm_instance.tag()} : {lm_instance}')
        self.lms_[lm_instance.tag()] = {
            "instance": lm_instance
        }
    def _deregister_lm(self, lm_instance):
        del self.lms_[lm_instance.tag()]

    def __apply_lm_recalculate_results(self, lm_tag, results: LMRecalculateResult):

        for child_tag in dpg.get_item_children(lm_tag, 1):
            if child_tag not in results:
                print(f"INFO: {child_tag} of type {dpg.get_item_type(child_tag)} was not allocated by the LayoutManager of tag {lm_tag} !")
                continue

            if self.is_lm_registered(child_tag):
                _EasyDPGWrapperFullGeometryController(child_tag).set_pos_x(results[child_tag]['pos_x']).set_pos_y(
                    results[child_tag]['pos_y']).set_width(results[child_tag]['width']).set_height(
                    results[child_tag]['height'])
            else:  # aici e logica preferentiala per camp
                child_meta_ = EasyDPGWrapper(child_tag)
                min_x_ = child_meta_.min_x()
                min_y_ = child_meta_.min_y()
                max_x_ = child_meta_.max_x()
                max_y_ = child_meta_.max_y()
                padding_left = child_meta_.padding_left()
                padding_right = child_meta_.padding_right()
                padding_top = child_meta_.padding_top()
                padding_bottom = child_meta_.padding_bottom()
                scale_x_ = child_meta_.scale_x()
                scale_y_ = child_meta_.scale_y()
                justify_x_ = child_meta_.justify_x()
                justify_y_ = child_meta_.justify_y()
                container_width_ = results[child_tag]['width']
                container_height_ = results[child_tag]['height']
                container_px_ = results[child_tag]['pos_x']
                container_py_ = results[child_tag]['pos_y']

                temp_width_ = scale_x_ * container_width_
                temp_height_ = scale_y_ * container_height_
                final_width_ = min(max_x_ if max_x_ > 0 else 10000000, max(min_x_ if min_x_ > 0 else 0, temp_width_))
                final_height_ = min(max_y_ if max_y_ > 0 else 10000000, max(min_y_ if min_y_ > 0 else 0, temp_height_))

                try:
                    print(f"{child_tag}: old f width si height {final_width_} {final_height_}")
                    size_ctrl_ = _EasyDPGWrapperSizeController(child_tag)
                    size_ctrl_.set_width(final_width_).set_height(final_height_)
                except:
                    pass

                try:
                    final_width_ = dpg.get_item_rect_size(child_tag)[0] # incercam sa le mai luam o data (la mvtext nu merge de asta try:except:) pentru ca intre a seta si a se aplica identic e o diferenta
                    final_height_ = dpg.get_item_rect_size(child_tag)[1]
                except:
                    pass

                final_pos_x = container_px_ + (abs(final_width_ - container_width_) / 2 if justify_x_ == 0 else (
                    padding_left if justify_x_ < 0 else container_width_ - final_width_ - padding_right))
                final_pos_y = container_py_ + (abs(final_height_ - container_height_) / 2 if justify_y_ == 0 else (
                    padding_top if justify_y_ < 0 else container_height_ - final_height_ - padding_bottom))

                _EasyDPGWrapperPositionController(child_tag).set_pos_x(final_pos_x).set_pos_y(final_pos_y)

                self.app_.render_frame()


    def __do_post_render_operations(self):

        # (e nevoie de) o prima recalculare LM-uri, la inceput
        if self.first_postrender_run_:
            #import pdb; pdb.set_trace()
            processing_queue_ = sorted([[tag, self.dfs_nodes_depth_[tag]] for tag in self.lms_.keys()],
                                       key=lambda x: x[1], reverse=False)
            for lm_meta_ in processing_queue_:
                instance_: _EasyDPGLayoutManagerBase = self.lms_[lm_meta_[0]]['instance']
                self.__apply_lm_recalculate_results(instance_.tag(), instance_.recalculate())
                print("render frame")
                self.app_.render_frame()

            self.first_postrender_run_ = False

        while True:

            # detectie redimensionare - inregistrare LM-uri 'atinse'
            for lm_tag in self.lms_.keys():
                if dpg.get_item_rect_size(lm_tag)[1] != self.lms_[lm_tag]['pre_height_'] or \
                        dpg.get_item_rect_size(lm_tag)[0] != self.lms_[lm_tag]['pre_width_']:
                    self.__add_resized_lm(lm_tag)

            # procesare Lm-uri 'atinse'
            if len(self.resized_lms_.keys()) > 0: # aici e toata treaba

                for lm_tag in self.lms_.keys():
                    self.lms_[lm_tag]['pre_height_'] = dpg.get_item_rect_size(lm_tag)[1]
                    self.lms_[lm_tag]['pre_width_'] = dpg.get_item_rect_size(lm_tag)[0]

                if any([tag not in self.dfs_nodes_depth_ for tag in self.resized_lms_.keys()]):
                    # postpone, internal data si not yet synced
                    print(f"WARNING: _LayoutManagerController: __do_post_render_operations: resized_lms_ tags are not yet registered in the tree !")
                else:
                    # 1 sortez lista dupa adancime si o transform sa stochez si adancimea - devine o coada de consum
                    processing_queue_ = sorted([[tag, self.dfs_nodes_depth_[tag]] for tag in self.resized_lms_.keys()], key=lambda x: x[1], reverse=False)

                    # 2 consum coada nivel cu nivel, si apelez app_render_frame() numai daca e diferenta mai mult de 1 intre nivelul curent si cel urmator
                    head_ = 0
                    c_depth_ = processing_queue_[head_][1]
                    while head_ < len(processing_queue_):
                        i = head_
                        while head_ < len(processing_queue_) and processing_queue_[head_][1] == c_depth_:
                            # 2.1. get width/height pe nod LM
                            lm_tag_ = processing_queue_[head_][0]
                            lm_: _EasyDPGLayoutManagerBase = self.lms_[lm_tag_]['instance']
                            # 2.2. recalculate pe nod LM
                            self.__apply_lm_recalculate_results(lm_.tag(), lm_.recalculate())
                            head_ += 1

                        if head_ >= len(processing_queue_):
                            print("render frame")
                            self.app_.render_frame()
                            break
                        if abs(c_depth_ - processing_queue_[head_][1]) > 1:
                            print("render frame")
                            self.app_.render_frame()
                        c_depth_ = processing_queue_[head_][1]

                    self.resized_lms_ = {}
            else:
                break

    def __do_pre_render_operations(self):

        # inregistrare dimensiuni inainte de randare (pentru detectie schimbari din partea mecanismului nativ dpg din render_frame)
        for lm_tag in self.lms_.keys():
            self.lms_[lm_tag]['pre_height_'] = dpg.get_item_rect_size(lm_tag)[1]
            self.lms_[lm_tag]['pre_width_'] = dpg.get_item_rect_size(lm_tag)[0]

        # la inceput, cream pomul DFS...
        if self.dfs_nodes_depth_ is None:
            self.__build_tree(build_children=True, build_depths=True, build_entry_exit_indexes=True) # pt prima oara (UI-ul e deja construit)
            self.__build_resize_callbacks()

        #import pdb; pdb.set_trace()
        # detectam descendenti noi (structura modificata) pentru a recrea pomul DFS
        for node_tag in self.dfs_nodes_children_count_.keys():
            
            try:
                child_count_ = len(dpg.get_item_children(node_tag, 1))
            except:
                # node_tag does not exist (so children removed event)
                print(f"eliminare descendent detectata: {node_tag}")
                must_recompute_structs_ = True
                break
            
            must_recompute_structs_ = False
            #print(f'{node_tag}: (current) {child_count_} vs {self.dfs_nodes_children_count_[node_tag]} (stored)')
            if child_count_ != self.dfs_nodes_children_count_[node_tag]:
                print(f"descendent detectat: {node_tag}")
                # de sus in jos, avem un nod care si-a modificat numarul de copii
                must_recompute_structs_ = True
                break
        if must_recompute_structs_:
            print("refacem structurile fiindca s-au modificat..., recalculam ?!")
            self.__build_tree(build_children=True, build_depths=True, build_entry_exit_indexes=True)  # @TODO erau bune actualizari selective, dar e treaba un pic mai complexa...
            self.__build_resize_callbacks()

    def __build_resize_callbacks(self):
        #print(f"adaugat callback-uri resized pt {self.lms_}")
        for lm_ in self.lms_.keys():
            self.__register_resize_handler(lm_)


    def __build_tree(self, root_node=None, build_entry_exit_indexes=False, build_depths=False, build_children=False):
        if root_node is None:
            root_node = self.app_.root_tag()

        # Inițializăm structurile pentru a stoca arborele și indecșii
        if build_entry_exit_indexes:
            self.entry_index_ = {}
            self.exit_index_ = {}

        if build_depths:
            self.dfs_nodes_depth_ = {}

        if build_children:
            self.dfs_nodes_children_count_ = {}

        index = 0

        # Funcție pentru parcurgerea în adâncime și calculul indecșilor
        def dfs_scan(node_tag, depth=0):
            nonlocal index

            if build_entry_exit_indexes:
                self.entry_index_[node_tag] = index

            if build_depths:
                self.dfs_nodes_depth_[node_tag] = depth

            children_ = dpg.get_item_children(node_tag, 1)
            if build_children:
                self.dfs_nodes_children_count_[node_tag] = len(children_)
            # print([dpg.get_item_configuration(child) for child in children_])
            index += 1
            for child in children_:  # Accesăm copiii itemului
                dfs_scan(child, depth + 1)

            if build_entry_exit_indexes:
                self.exit_index_[node_tag] = index

        dfs_scan(root_node)

    def __add_resized_lm(self, tag): print(f"adaug lm la resized-list: {tag}"); self.resized_lms_[tag] = True # ma intereseaza doar hash-ul, deci valoarea e dummy

    def __register_resize_handler(self, tag):
        try:
            id_ = int(random.random() * 10000)
            with dpg.item_handler_registry(tag=f"{tag}-{id_}_resizer"):
                #dpg.add_item_resize_handler(callback=lambda: print(f"s-a redimensionat item-ul {tag} {dpg.get_item_alias(tag)}"))
                dpg.add_item_resize_handler(callback=lambda: self.__add_resized_lm(tag))
            dpg.bind_item_handler_registry(tag, f"{tag}-{id_}_resizer")

        except Exception as e:
            print(f"ERROR: could not call dpg.item_handler_registry and .bind_item_handler_registry on tag {tag} but it should have worked: {str(e)}")


#####################################################
# LOGICA DI
from injector import Injector, inject, provider, Module, singleton

class EasyDPGModule(Module):
    @singleton
    @provider
    def provide_root_app(self, configurator: EasyDPGAppConfigurator) -> EasyDPGApp:
        return EasyDPGApp(configurator=configurator)

    @singleton
    @provider
    def provide_layout_manager_ctrl(self) -> _LayoutManagerController:
        return _LayoutManagerController()

from .generic_utils import abstract_factory
from functools import partial

_FACTORY = partial(abstract_factory, _globals=globals(), _locals=locals())

_easydpg_injector = None
def FACTORY(cls, *args, **kwargs):
    global _easydpg_injector
    if _easydpg_injector is None:
        _easydpg_injector = Injector([_configure_app, EasyDPGModule])
    return _FACTORY(injector = _easydpg_injector, cls=cls, *args, **kwargs)

#####################################################

## PUBLIC METHOD
def create_app(background_color: UniversalColor = (0.5,0.5,0.5,1.0), pos=None, size=["70%", "70%"], fullscreen=False):
    #global _APP_BACKGROUND_COLOR
    if "_APP_BACKGROUND_COLOR" not in globals():
        globals()['_APP_BACKGROUND_COLOR'] = (0.5,0.5,0.5,0.5)
    if "_APP_POS" not in globals():
        globals()['_APP_POS'] = (0, 0)
    if "_APP_SIZE" not in globals():
        globals()['_APP_SIZE'] = ('100%', '100%')
    if "_APP_FULLSCREEN" not in globals():
        globals()['_APP_FULLSCREEN'] = False

    globals()['_APP_BACKGROUND_COLOR'] = background_color
    globals()['_APP_POS'] = tuple(pos) if pos is not None else None
    globals()['_APP_SIZE'] = tuple(size) if size is not None else None
    globals()['_APP_FULLSCREEN'] = fullscreen is True

    return FACTORY(EasyDPGApp)
#####################################################

class _EasyDPGWrapperContainer:
    def __init__(self, tag):
        self.tag_ = tag
        _guard_incompatible_type(tag, _CONTEXT_MANAGEABLE_DPG_ITEMS)

    def __enter__(self):
        dpg.push_container_stack(self.tag_); return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None or exc_val is not None or exc_tb is not None:
            print(f"ERROR: _EasyDPGWrapperContainer: exception on tag {self.tag_}, during managed context execution: {exc_type}: {exc_val}:\n{exc_tb}")
        dpg.pop_container_stack()

    def delete(self): dpg.delete_item(self.tag_); return self
    def delete_children(self): dpg.delete_item(self.tag_, children_only=True); return self

    def move_child_here(self, tag: Union[str, int]):
        dpg.move_item(tag, parent=self.tag_)

class _EasyDPGWrapperVisibility:
    def __init__(self, tag):
        _guard_incompatible_type(tag, _VISIBILITY_DPG_ITEMS)
        self.tag_ = tag

    def is_visible(self): return dpg.is_item_visible(self.tag_); return self
    def set_visible(self, visible: bool):
        if visible:
            self.show()
        else:
            self.hide()
        return self
    def show(self): dpg.show_item(self.tag_); return self
    def hide(self): dpg.hide_item(self.tag_); return self

class _EasyDPGWrapperSingleValueController:
    def __init__(self, tag):
        _guard_incompatible_type(tag, _SINGLEVALUE_DPG_ITEMS)
        self.tag_ = tag

    def value(self): return dpg.get_value(self.tag_)
    def set_value(self, value): dpg.set_value(self.tag_, value); return self

class _EasyDPGWrapperPositionController:
    def __init__(self, tag):
        #_guard_incompatible_type(tag, ) # all can be positioned
        self.tag_ = tag

    def set_pos_y(self, pos_y: int):
        pos_ = dpg.get_item_pos(self.tag_)
        pos_[1] = pos_y
        dpg.set_item_pos(self.tag_, pos_)
        return self

    def set_pos_x(self, pos_x: int):
        pos_ = dpg.get_item_pos(self.tag_)
        pos_[0] = pos_x
        dpg.set_item_pos(self.tag_, pos_)
        return self

    def pos_x(self): return dpg.get_item_pos(self.tag_)[0]
    def pos_y(self): return dpg.get_item_pos(self.tag_)[1]

class _EasyDPGWrapperSizeController:
    def __init__(self, tag, external_resize_listener = lambda real_width, real_height: None):
        _guard_incompatible_type(tag, _GEOMETRY_SIZE_MANAGEABLE_DPG_ITEMS)
        self.tag_ = tag

    def width(self):
        return dpg.get_item_width(self.tag_)

    def height(self):
        return dpg.get_item_height(self.tag_)

    def real_height(self):
        return dpg.get_item_rect_size(self.tag_)[1]

    def real_width(self):
        return dpg.get_item_rect_size(self.tag_)[0]

    def set_width(self, width: int):
        dpg.configure_item(self.tag_, width=width); return self

    def increase_width(self, more_width_percent_or_scalar: Union[int, float]):
        self.set_width(self.width() + (
            more_width_percent_or_scalar if type(more_width_percent_or_scalar) is int else int(
                self.width() * more_width_percent_or_scalar)))
        return self

    def set_height(self, height: int):
        #print(f"setting height for {self.tag_} ({dpg.get_item_type(self.tag_)}): {height}")
        dpg.configure_item(self.tag_, height=height); return self

    def increase_height(self, more_height_percent_or_scalar: Union[int, float]):
        self.set_height(self.height() + (
            more_height_percent_or_scalar if type(more_height_percent_or_scalar) is int else int(
                self.height() * more_height_percent_or_scalar)))
        return self

class _EasyDPGWrapperFullGeometryController(_EasyDPGWrapperPositionController, _EasyDPGWrapperSizeController):
    def __init__(self, tag, external_resize_listener = lambda real_width, real_height: None):
        _EasyDPGWrapperPositionController.__init__(self, tag)
        _EasyDPGWrapperSizeController.__init__(self, tag, external_resize_listener)


class _EasyDPGDefaultCallback:
    def __init__(self, tag, is_submit_valid: lambda tag, app, user_data: True, validate_submit: lambda tag, app, user_data: True, get_submit_value: lambda tag, app, user_data: None):
        _guard_incompatible_type(tag, _DEFCALLBACK_DPG_ITEMS)
        self.tag_ = tag

        self.is_submit_valid_ = is_submit_valid
        self.validate_submit_ = validate_submit
        self.get_submit_value_ = get_submit_value

        self.preregistered_submit_callback_ = dpg.get_item_callback(self.tag_)
        self.custom_submit_callback_ = lambda tag, selections: None
        dpg.set_item_callback(tag, self.__submit_callback)

    def __submit_callback(self, tag, app_data, user_data):
        if self.is_submit_valid_(tag, app_data, user_data):
            self.validate_submit_(tag, app_data, user_data)

            if self.preregistered_submit_callback_ is not None:
                self.preregistered_submit_callback_(tag, app_data, user_data)
            self.custom_submit_callback_(tag, self.get_submit_value_(tag, app_data, user_data))

    def set_submit_callback(self, callback: lambda tag, value: None):
        if self.preregistered_submit_callback_ is not None: # previous callback set,
            print(f"INFO: _EasyDPGDefaultCallback: set_submit_callback: you also have a previous callback (before wrapping) set, so you could call remove_preregistered_submit_callback to remove that and to remain with the current one only, if you want ...")

        self.custom_submit_callback_ = callback; return self

    def remove_preregistered_submit_callback(self, callback: lambda tag, app_data, user_data: None):
        self.preregistered_submit_callback_ = None; self.custom_submit_callback_ = callback; return self

######################################################################
# CONCRETE UI (NATIVE) WIDGETS
####################################

# GENERIC CLASS
class EasyDPGWrapper:

    def __init__(self, tag: Union[str, int]):
        if tag is None:
            raise Exception(f'ERROR: EasyDPGWrapper: __init__: abnormal situation -> provided tag is None')
        if type(tag) != str and type(tag) != int:
            raise Exception(f"EasyDPGWrapper: provided tag {tag} is not an int or a str, could it be that you passed an already wrapped tag in another EasyDPGWrapper ?!...")
        self.tag_ = tag

        ud_ = dpg.get_item_user_data(tag)
        ud_ = {} if ud_ is None else ud_
        ud_ = {**{
            'scale_x': 1.0, # pt LM-uri, cum sa se incadreze in spatiul virtual dat de LM
            'scale_y': 1.0,
            'justify_x': -1, # tot pt LM-uri, 0 e centru, -1 e stanga, 1 e dreapta
            'justify_y': -1,
            'min_x': 0, # tot pt LM-uri, limitele preferentiale sub care LM-ul nu mai scaleaza elementul; cealalta, limita maxima peste care nu o mai scaleaza...
            'max_x': 0,
            'min_y': 0,
            'max_y': 0,
            'padding_left': 0,
            'padding_right': 0,
            'padding_top': 0,
            'padding_bottom': 0,
        }, **ud_}
        dpg.set_item_user_data(tag, ud_)

    def scale_x(self): return dpg.get_item_user_data(self.tag_)['scale_x']
    def scale_y(self): return dpg.get_item_user_data(self.tag_)['scale_y']
    def justify_x(self): return dpg.get_item_user_data(self.tag_)['justify_x']
    def justify_y(self): return dpg.get_item_user_data(self.tag_)['justify_y']
    def min_x(self): return dpg.get_item_user_data(self.tag_)['min_x']
    def min_y(self): return dpg.get_item_user_data(self.tag_)['min_y']
    def max_x(self): return dpg.get_item_user_data(self.tag_)['max_x']
    def max_y(self): return dpg.get_item_user_data(self.tag_)['max_y']
    def padding_left(self): return dpg.get_item_user_data(self.tag_)['padding_left']
    def padding_right(self): return dpg.get_item_user_data(self.tag_)['padding_right']
    def padding_top(self): return dpg.get_item_user_data(self.tag_)['padding_top']
    def padding_bottom(self): return dpg.get_item_user_data(self.tag_)['padding_bottom']
    def set_scale_x(self, new_scale):
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['scale_x'] = new_scale
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_scale_y(self, new_scale):
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['scale_y'] = new_scale
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_justify_x(self, justify):
        '''
        Sets justify value (for LMs) for X axis
        :justify 0 center, 1 right, -1 left
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['justify_x'] = justify
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_justify_y(self, justify):
        '''
        Sets justify value (for LMs) for Y axis
        :justify 0 center, 1 right, -1 left
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['justify_y'] = justify
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_min_x(self, limit):
        '''
        Sets minimal value (for LMs) for X axis scale (preferential min limit)
        :limit 0 means disabled (scaling is never stopped), strict pozitive value is a valid limiting value for the scale
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['min_x'] = limit
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_min_y(self, limit):
        '''
        Sets minimal value (for LMs) for Y axis scale (preferential min limit)
        :limit 0 means disabled (scaling is never stopped), strict pozitive value is a valid limiting value for the scale
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['min_y'] = limit
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_max_x(self, limit):
        '''
        Sets maximal value (for LMs) for X axis scale (preferential max limit)
        :limit 0 means disabled (scaling is never stopped), strict pozitive value is a valid limiting value for the scale
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['max_x'] = limit
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_max_y(self, limit):
        '''
        Sets maximal value (for LMs) for Y axis scale (preferential max limit)
        :limit 0 means disabled (scaling is never stopped), strict pozitive value is a valid limiting value for the scale
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['max_y'] = limit
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_padding_left(self, padding):
        '''
        Sets padding value (for LMs) for the left side
        :padding any int pixels value
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['padding_left'] = padding
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_padding_right(self, padding):
        '''
        Sets padding value (for LMs) for the right side
        :padding any int pixels value
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['padding_right'] = padding
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_padding_top(self, padding):
        '''
        Sets padding value (for LMs) for the top side
        :padding any int pixels value
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['padding_top'] = padding
        dpg.set_item_user_data(self.tag_, ud_)
        return self
    def set_padding_bottom(self, padding):
        '''
        Sets padding value (for LMs) for the bottom side
        :padding any int pixels value
        '''
        ud_ = dpg.get_item_user_data(self.tag_)
        ud_['padding_bottom'] = padding
        dpg.set_item_user_data(self.tag_, ud_)
        return self

    @staticmethod
    def validate_tag(tag):
        try:
            dpg.get_item_type(tag)
            return True
        except Exception as e:
            return False

    def tag(self):
        return self.tag_



def _get_valid_parent(explicit_parent: DPGParent):
    if explicit_parent is not None and not EasyDPGWrapper.validate_tag(explicit_parent):
        raise Exception(
            f'ERROR: EasyDPG (module): _get_valid_parent: invalid parent tag given: {explicit_parent}')

    try:
        current_container = dpg.pop_container_stack()
        dpg.push_container_stack(current_container)
        if explicit_parent is not None:  # have current container, and, also explicit_parent ?
            raise Exception(
                "ERROR: EasyDPG (module): _get_valid_parent: misuse, already in am implicit container (has a 'with' clause above it) but you also provided a valid explicit_parent param; if you want an explicit parent to be taken into account, please throw this build instruction outside the with clauses first !")

        return current_container, 'implicit'
    except:
        if explicit_parent is None:
            raise Exception(
                "ERROR: EasyDPG (module): _get_valid_parent: misuse, expected a parent tag (and a valid) one, since you are NOT in an implicit container; cannot create this element without referencing it under a certain container (parent)")

    return explicit_parent, 'explicit'

def _try_inject_explicit_parent(explicit_parent: AnyParent, params: dict):
    parent, parent_type_ = _get_valid_parent(explicit_parent if type(explicit_parent) in [int, str] or explicit_parent is None else explicit_parent.tag())
    if parent_type_ == "explicit":  # else without specifying a parent, the implicit container (from active context manager) should work by itself, and this is the default, so we are making it this way also
        params['parent'] = parent

    return params

class EasyDPGWrapperFileDialog(EasyDPGWrapper, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperVisibility, _EasyDPGDefaultCallback):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)

        def _is_submit_valid(tag, app_data, user_data):
            single_selection_ = user_data['single_selection'] if 'single_selection' in user_data else False
            current_selections_ = list(app_data["selections"].values())
            if single_selection_ and len(current_selections_) > 1:
                error_or_info_box("You must make only one selection, please try again !", lambda: self.open(),
                                  is_info_box=False)
                return False
            return True
        def _validate_submit(tag, app_data, user_data):
            self.target_ = list(app_data["selections"].values())
        def __pprocess_selections(tag, selections):
            for_dirs_ = dpg.get_item_configuration(tag)['directory_selector']
            if for_dirs_: # nu stiu de ce, la directoare, imi duplica ultimul subdirector file_dialog-ul din dpg..., deci trebuie aceasta corectie
                result_ = []
                for s in selections:
                    parts_ = s.split(os.path.sep)
                    result_.append(os.path.sep.join(parts_[:-1]))
                return result_
            else:
                return selections
        def _get_submit_value(tag, app_data, user_data): print(app_data); print(app_data['selections']); return __pprocess_selections(tag, list(app_data["selections"].values()))

        _EasyDPGDefaultCallback.__init__(self, tag, is_submit_valid=_is_submit_valid, validate_submit=_validate_submit, get_submit_value=_get_submit_value)

        _guard_incompatible_type(tag, ['mvfiledialog'])

        self.target_ = None

        self.custom_cancel_callback_ = lambda tag: None # TODO, din pacate, nu pot face aceeasi poanta cu cancel_callback, care, desi exista, este un bug in dpg si nu este predat cu dpg.get_item_configuration (au uitat sa-l publice in acest dictionar)
        # @TODO problema e ca daca a fost setat un callback de cancel inainte, eu acum nu-l pot prelua ca sa-l salvez si punand pe al lui self, in locul lui, il suprascriu pe acela...
        #self.preregistered_cancel_callback_ = # @TODO
        dpg.configure_item(self.tag_, cancel_callback=self.__cancel_callback)

    def __cancel_callback(self, tag, app_data, user_data):
        self.target_ = None
        self.custom_cancel_callback_(tag)

    def set_cancel_callback(self, callback: lambda tag: None):
        #if self.previous_submit_callback_ is not None: # previous callback set, # @TODO dpg has a bug, so cannot activate this until fixed, see the comments from the constructor
        #    print(f"INFO: EasyDPGWrapperFileDialog: set_cancel_callback: you also have a previous callback (before wrapping) set, so you could call remove_preregistered_cancel_callback to remove that and to remain with the current one only, if you want ...")
        self.custom_cancel_callback_ = callback; return self

    #def remove_preregistered_cancel_callback(self, callback: lambda tag, app_data, user_data: None): # TODO dpg is faulty, when the bug will be fixed, this can be activated
    #    self.previous_cancel_callback_ = None; return self

    def selections(self): return self.target_
    def selection(self): return self.target_[0]

    def open(self): return self.show()

    @staticmethod
    def build(width=100, height=30, dialog_type: Union[Literal["file", "dir", "directory"]]="file", start_path = None, file_filters=[".*"], single_selection=True) -> 'EasyDPGWrapperFileDialog':
        """
        Crează un filedialog simplificat cu parametrii esențiali.
        :param width: Lățimea dialogului.
        :param height: Înălțimea dialogului.
        """
        params_ = {
            "width": width,
            "height": height,
            "directory_selector": dialog_type.lower() != "file",
            "show": False, # initial nu arati nimic, dar poti apela metoda open() ca sa il arati
            "modal": True, # nu vad rostul sa nu fie modal, de vreme ce inseamna sa-si piarda focalizarea, dar fiindca fereastra asta nu se poate pozitiona permanent undeva, atunci e clar, se deschide, iti faci treaba cu ea nestingherit si o inchizi; daca modal=False are vreo noima, se poate inventa o metoda set_modal cu dpg.configure(item...)
            "user_data": {
                "single_selection": single_selection
            }
        }
        if start_path is not None and os.path.exists(start_path):
            params_['default_path'] = start_path
        elif start_path is not None:
            print(f"WARNING: start_path ('{start_path}') is an invalid path; it was ignored !")

        element_id = dpg.add_file_dialog(**params_)
        for filter in file_filters:
            dpg.add_file_extension(filter, parent=element_id)

        #dpg.add_file_extension(".txt", color=(255, 255, 255, 255), custom_text="[Text Files]", parent=element_id)

        return EasyDPGWrapperFileDialog(tag=element_id)

class EasyDPGWrapperText(EasyDPGWrapper, _EasyDPGWrapperVisibility):
    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ['mvtext'])

    def text(self): return dpg.get_value(self.tag_)
    def set_text(self, text): dpg.set_value(self.tag_, text); return self

    @staticmethod
    def build(text, explicit_parent: AnyParent=None) -> 'EasyDPGWrapperText':
        """
        Crează un text (label) simplificat cu parametrii esențiali.
        :param text: Textul reprezentat.
        :param explicit_parent: Containerul părinte în care se va plasa text-ul (eticheta).
        :param width: Lățimea etichetei.
        :param height: Înălțimea etichetei.
        """
        params_ = {
            "default_value": text
        }

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_text(**params_)

        return EasyDPGWrapperText(tag=element_id)

class EasyDPGWrapperCheckbox(EasyDPGWrapper, _EasyDPGWrapperSingleValueController, _EasyDPGWrapperVisibility, _EasyDPGDefaultCallback):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperSingleValueController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGDefaultCallback.__init__(self, tag, is_submit_valid=lambda t,a,u: True, validate_submit=lambda t,a,u: None, get_submit_value=lambda t,a,u: dpg.get_value(t))

        _guard_incompatible_type(self.tag(), ["mvcheckbox"])


    @staticmethod
    def build(label: str, explicit_parent: AnyParent=None, default_value: bool = False) -> 'EasyDPGWrapperCheckbox':
        """
        Crează un buton de checkbox simplificat cu parametrii esențiali.
        :param label: Textul de pe buton.
        :param explicit_parent: Containerul părinte în care se va plasa butonul.
        """
        params_ = {
            "label": label,
            "default_value": default_value
        }

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_checkbox(**params_)

        return EasyDPGWrapperCheckbox(tag=element_id)


class EasyDPGWrapperGroup(EasyDPGWrapper, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperVisibility, _EasyDPGWrapperContainer):

    def __init__(self, tag, external_resize_listener=lambda real_width, real_height: None):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag, external_resize_listener=external_resize_listener)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperContainer.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ["mvgroup"])

    @staticmethod
    def build(type: Literal["horizontal", "vertical", "horiz", "vert", "h", "v"], width=None, height=None, explicit_parent: AnyParent = None) -> 'EasyDPGWrapperGroup':
        """
        Crează un grup (container invizibil) simplificat cu parametrii esențiali.
        :param type: horizontal('horizontal', 'h', 'horiz') sau vertical('vertical', 'v', 'vert')
        :param width: Lățimea grupului (e o constrangere, face ca toate elementele sa se redistribuie proportional).
        :param height: Înălțimea grupului (e o constrangere, face ca toate elementele sa se redistribuie proportional).
        :param explicit_parent: Containerul părinte în care se va plasa containerul de aranjare invizibil.
        """
        params_ = {
            "horizontal": True if type.lower() in ['horizontal', 'horiz', 'h'] else False
        }
        if width is not None:
            params_['width'] = width
        if height is not None:
            params_['height'] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_group(**params_)

        return EasyDPGWrapperGroup(tag=element_id)

# NOTA: eu cum am gandit panoul asta e ca parte din structura principala a unui ecran, deci l-am gandit static (desi dpg.window are muulte optiuni dinamice), de ex ideea de title_bar:True si collapsible te lasa sa minimizezi panoul, dar daca eu ti-l cer ca si configuratie, cu pozitie si dimensiuni statice, nu te voi lasa (de la build(...)) sa il faci colapsibil etc; ci daca vrei asta, posibil ca te voi lasa prin metode dinamice, gen move(...), resize(...), minimize(), maximize() etc
# @TODO... vezi nota de mai sus, si fa metodele alea propuse
class EasyDPGWrapperPrimaryPanel(EasyDPGWrapper, _EasyDPGWrapperVisibility, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperContainer, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperContainer.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_window_theme)

        _guard_incompatible_type(self.tag(), ["mvwindowappitem"])

    def set_resizable(self): dpg.configure_item(self.tag_, autosize=False, no_resize=False); return self
    def set_fixed(self): dpg.configure_item(self.tag_, no_resize=True, no_move=True); return self
    def set_movable(self): dpg.configure_item(self.tag_, no_move=False); return self

    def set_transparent(self): dpg.configure_item(self.tag_, no_background=True); return self
    def set_opaque(self): dpg.configure_item(self.tag_, no_background=False); return self

    @staticmethod
    def build(label=None, width:int=None, height:int=None, pos: Union[List[int], Tuple[int, ...]] = (0, 0), visible_scrollbars: Union[Literal["vh", "hv", "v", "", "none", "ji", "just_implicit", "i"], None] = None, completely_transparent: bool = False, background_color_hue_or_rgb_and_or_alpha: UniversalColor = None) -> 'EasyDPGWrapperPrimaryPanel':
        """
        Crează un panou primar (asezat direct in fereastra aplicatiei) - e o fereastra dpg fara bara sus si complet imobila.
        :param label: titlul panoului; daca e lasat pe None, nu o sa mai apara, in general, bara de titlu cu tot cu titlu; daca e un string valid, o sa apara bara de titlu, doar cu acest titlu
        :param width: Lățimea panoului -> daca nu e specificata, autosize o sa fie pe True
        :param height: Înălțimea panoului -> daca nu e specificata, autosize o sa fie pe True
        :param pos: tuplu sau lista de 2 elemente, cu x si y, pozitia relativa la radacina (le fereastra OS-ului, a aplicatiei), implicit 0,0, coltul stanga-sus
        :param visible_scrollbars: sunt doar trei variante care functioneaza in dpg, privind vizibilitatea scroll-urilor: ambele (vertical si orizontal), doar vertical, niciunul, si mai adaug eu, doar-implicit (doar prin mouse, fara derulatori vizibili)
        :param completely_transparent: daca e True, nu va fi culoare de fundal, ci totul va fi transparent complet, in interiorul acestui container (panou)
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """

        visible_scrollbars = visible_scrollbars.strip().lower() if visible_scrollbars is not None else ""
        has_title_ = label is not None and type(label) is str and len(label) > 0

        has_explicit_size_ = width is not None or height is not None

        params_ = {
            "label": label if has_title_ else "",
            "pos": pos,
            "autosize": False if has_explicit_size_ else True,
            "no_background": completely_transparent,

            "menubar": False, # aceste caracteristici fac fereastra dpg un panou primar...
            "collapsed": False,
            "no_collapse": True,
            "no_resize": True, # asta se va putea dezactiva/activa programatic... (de ex, dai drumul la un mod de reorganizare layout UI, personalizabil si faci cumva sa retii noile pozitii si marimi)
            "no_move": True, # idem cu no_resize
            "no_title_bar": False if has_title_ else True,
            "no_close": True,
            "modal": False,
            "popup": False,
        }
        if visible_scrollbars in ['ji', 'i', 'just_implicit']:
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = False
        elif visible_scrollbars in ['none', '']: # None e implicit gestionat mai sus
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = True
        else:
            params_["no_scroll_with_mouse"] = False
            if visible_scrollbars == 'v':
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = False
            elif visible_scrollbars in ['vh', 'hv']:
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = True
            else:
                print(f"WARNING: EasyDPGWrapperPrimaryPanel: build: didn't recognized visible_scrollbars parameter: {visible_scrollbars}")

        if has_explicit_size_:
            if width is not None:
                params_['width'] = width
            if height is not None:
                params_['height'] = height

        element_id = dpg.add_window(**params_)

        ref_ = EasyDPGWrapperPrimaryPanel(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb_and_or_alpha)
        return ref_

class EasyDPGWrapperInnerPanel(EasyDPGWrapper, _EasyDPGWrapperVisibility, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperContainer, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperContainer.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_child_window_theme)

        _guard_incompatible_type(self.tag(), ["mvchildwindow"])

    def activate_border(self): dpg.configure_item(self.tag_, border=True); return self
    def deactivate_border(self): dpg.configure_item(self.tag_, border=False); return self

    @staticmethod
    def build(label=None, width: int=None, height: int=None, pos: Union[List[int], Tuple[int, ...], None] = None, visible_scrollbars: Union[Literal["vh", "hv", "v", "", "none", "ji", "just_implicit", "i"], None] = None, show_borders: bool = True, background_color_hue_or_rgb_and_or_alpha: UniversalColor = None, explicit_parent: AnyParent=None) -> 'EasyDPGWrapperInnerPanel':
        """
        Crează un panou de interior e o fereastra dpg fara bara sus si complet imobila, cel putin in prima faza, dar plasata sub o alta fereastra (panou interior sau panou primar/principal)
        :param explicit_parent: Containerul părinte în care se va plasa panoul.
        :param label: titlul panoului; daca e lasat pe None, nu o sa mai apara, in general, bara de titlu cu tot cu titlu; daca e un string valid, o sa apara bara de titlu, doar cu acest titlu
        :param width: Lățimea panoului -> daca nu e specificata, se duce, automat, pe toata lungimea containerului parinte
        :param height: Înălțimea panoului -> daca nu e specificata, se duce, automat, pe toata inaltimea containerului parinte
        :param pos: tuplu sau lista de 2 elemente, cu x si y, pozitia relatival a radacina (le fereastra OS-ului, a aplicatiei), implicit 0,0, coltul stanga-sus
        :param visible_scrollbars: sunt doar trei variante care functioneaza in dpg, privind vizibilitatea scroll-urilor: ambele (vertical si orizontal), doar vertical, niciunul, si mai adaug eu, doar-implicit (doar prin mouse, fara derulatori vizibili)
        :param show_borders: daca e False, bordurile nu o sa mai apara, implicit True
        """

        visible_scrollbars = visible_scrollbars.strip().lower() if visible_scrollbars is not None else ""
        has_title_ = label is not None and type(label) is str and len(label) > 0
        has_explicit_width_ = width is not None
        has_explicit_height_ = height is not None
        has_explicit_size_ = has_explicit_width_ or has_explicit_height_

        params_ = {
            "label": label if has_title_ else "",
            "border": show_borders,

            "menubar": False # ... ?!,
        }
        if pos is not None:
            params_["pos"] = pos

        if visible_scrollbars in ['ji', 'i', 'just_implicit']:
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = False
        elif visible_scrollbars in ['none', '']: # None e implicit gestionat mai sus
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = True
        else:
            params_["no_scroll_with_mouse"] = False
            if visible_scrollbars == 'v':
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = False
            elif visible_scrollbars in ['vh', 'hv']:
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = True
            else:
                print(f"WARNING: EasyDPGWrapperInnerPanel: build: didn't recognized visible_scrollbars parameter: {visible_scrollbars}")

        #"autosize_x": (autosize is None and not has_explicit_width_) or autosize is True, # la child_window, nu e nevoie (dupa testele mele practice) de autosize_x/y fiindca sunt implicite, practic, sunt pe True, daca lipseste width/height si False, daca dai explicit width sau height, par sa fie syntactic sugar... (mai merita reconfirmat dar asa imi pare mie)
        #"autosize_y": (autosize is None and not has_explicit_height_) or autosize is True,

        if has_explicit_size_:
            if width is not None:
                params_['width'] = width
            if height is not None:
                params_['height'] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_child_window(**params_)

        #print(f"{element_id}: has_explicit_width_: {has_explicit_width_}")
        #print(f"{element_id}: has_explicit_height_: {has_explicit_height_}")

        ref_ = EasyDPGWrapperInnerPanel(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb_and_or_alpha)
        return ref_

class EasyDPGWrapperPopup(EasyDPGWrapper, _EasyDPGWrapperVisibility, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperContainer):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperContainer.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ["mvwindowappitem"])

    @staticmethod
    def build(label=None, width=None, height=None, pos: Union[List[int], Tuple[int, ...]] = (0, 0), visible_scrollbars: Union[Literal["vh", "hv", "v", "", "none", "ji", "just_implicit", "i"], None] = None, completely_transparent: bool = False) -> 'EasyDPGWrapperPopup':
        """
        Crează un panou primar (asezat direct in fereastra aplicatiei) - e o fereastra dpg fara bara sus si complet imobila.
        :param label: titlul panoului; daca e lasat pe None, nu o sa mai apara, in general, bara de titlu cu tot cu titlu; daca e un string valid, o sa apara bara de titlu, doar cu acest titlu
        :param width: Lățimea panoului -> daca nu e specificata, autosize o sa fie pe True
        :param height: Înălțimea panoului -> daca nu e specificata, autosize o sa fie pe True
        :param pos: tuplu sau lista de 2 elemente, cu x si y, pozitia relatival a radacina (le fereastra OS-ului, a aplicatiei), implicit 0,0, coltul stanga-sus
        :param visible_scrollbars: sunt doar trei variante care functioneaza in dpg, privind vizibilitatea scroll-urilor: ambele (vertical si orizontal), doar vertical, niciunul, si mai adaug eu, doar-implicit (doar prin mouse, fara derulatori vizibili)
        :param completely_transparent: daca e True, nu va fi culoare de fundal, ci totul va fi transparent complet, in interiorul acestui container (panou)
        """

        visible_scrollbars = visible_scrollbars.strip().lower() if visible_scrollbars is not None else ""
        has_title_ = label is not None and type(label) is str and len(label) > 0
        has_explicit_size_ = width is not None or height is not None

        params_ = {
            "label": label if has_title_ else "",
            "pos": pos,
            "autosize": False if has_explicit_size_ else True,
            "no_background": completely_transparent,

            "menubar": False, # aceste caracteristici fac fereastra dpg un panou primar...
            "collapsed": False,
            "no_collapse": True,
            "no_resize": True, # asta se va putea dezactiva/activa programatic... (de ex, dai drumul la un mod de reorganizare layout UI, personalizabil si facicumva sa retii noile pozitii si marimi)
            "no_move": True, # idem cu no_resize
            "no_title_bar": False if has_title_ else True,
            "no_close": True,
            "modal": False,

            "popup": True,
        }
        if visible_scrollbars in ['ji', 'i', 'just_implicit']:
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = False
        elif visible_scrollbars in ['none', '']: # None e implicit gestionat mai sus
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = True
        else:
            params_["no_scroll_with_mouse"] = False
            if visible_scrollbars == 'v':
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = False
            elif visible_scrollbars in ['vh', 'hv']:
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = True
            else:
                print(f"WARNING: EasyDPGWrapperPrimaryPanel: build: didn't recognized visible_scrollbars parameter: {visible_scrollbars}")

        if has_explicit_size_:
            if width is not None:
                params_['width'] = width
            if height is not None:
                params_['height'] = height

        element_id = dpg.add_window(**params_)

        return EasyDPGWrapperPopup(tag=element_id)


class EasyDPGWrapperModal(EasyDPGWrapper, _EasyDPGWrapperVisibility, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperContainer):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperContainer.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ["mvwindowappitem"])

    @staticmethod
    def build(label=None, width=None, height=None, pos: Union[List[int], Tuple[int, ...]] = (0, 0), visible_scrollbars: Union[Literal["vh", "hv", "v", "", "none", "ji", "just_implicit", "i"], None] = None, completely_transparent: bool = False) -> 'EasyDPGWrapperModal':
        """
        Crează un panou primar (asezat direct in fereastra aplicatiei) - e o fereastra dpg fara bara sus si complet imobila.
        :param label: titlul panoului; daca e lasat pe None, nu o sa mai apara, in general, bara de titlu cu tot cu titlu; daca e un string valid, o sa apara bara de titlu, doar cu acest titlu
        :param width: Lățimea panoului -> daca nu e specificata, autosize o sa fie pe True
        :param height: Înălțimea panoului -> daca nu e specificata, autosize o sa fie pe True
        :param pos: tuplu sau lista de 2 elemente, cu x si y, pozitia relatival a radacina (le fereastra OS-ului, a aplicatiei), implicit 0,0, coltul stanga-sus
        :param visible_scrollbars: sunt doar trei variante care functioneaza in dpg, privind vizibilitatea scroll-urilor: ambele (vertical si orizontal), doar vertical, niciunul, si mai adaug eu, doar-implicit (doar prin mouse, fara derulatori vizibili)
        :param completely_transparent: daca e True, nu va fi culoare de fundal, ci totul va fi transparent complet, in interiorul acestui container (panou)
        """

        visible_scrollbars = visible_scrollbars.strip().lower() if visible_scrollbars is not None else ""
        has_title_ = label is not None and type(label) is str and len(label) > 0
        has_explicit_size_ = width is not None or height is not None

        params_ = {
            "label": label if has_title_ else "",
            "pos": pos,
            "autosize": False if has_explicit_size_ else True,
            "no_background": completely_transparent,

            "menubar": False, # aceste caracteristici fac fereastra dpg un panou primar...
            "collapsed": False,
            "no_collapse": True,
            "no_resize": True, # asta se va putea dezactiva/activa programatic... (de ex, dai drumul la un mod de reorganizare layout UI, personalizabil si facicumva sa retii noile pozitii si marimi)
            "no_move": True, # idem cu no_resize
            "no_title_bar": False if has_title_ else True,
            "no_close": True,
            "popup": False,

            "modal": True,
        }
        if visible_scrollbars in ['ji', 'i', 'just_implicit']:
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = False
        elif visible_scrollbars in ['none', '']: # None e implicit gestionat mai sus
            params_["no_scrollbar"] = True
            params_["horizontal_scrollbar"] = False
            params_["no_scroll_with_mouse"] = True
        else:
            params_["no_scroll_with_mouse"] = False
            if visible_scrollbars == 'v':
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = False
            elif visible_scrollbars in ['vh', 'hv']:
                params_["no_scrollbar"] = False
                params_["horizontal_scrollbar"] = True
            else:
                print(f"WARNING: EasyDPGWrapperPrimaryPanel: build: didn't recognized visible_scrollbars parameter: {visible_scrollbars}")

        if has_explicit_size_:
            if width is not None:
                params_['width'] = width
            if height is not None:
                params_['height'] = height

        element_id = dpg.add_window(**params_)

        return EasyDPGWrapperModal(tag=element_id)

class EasyDPGWrapperSpacer(EasyDPGWrapper, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperVisibility):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ["mvspacer"])

    @staticmethod
    def build(width=100, height=0, pos: Union[List[int], Tuple[int, ...]] = None, explicit_parent: AnyParent = None) -> 'EasyDPGWrapperSpacer':
        """
        Crează un spatiator cu parametrii esențiali.
        :param width: Lățimea spatiatorului - se pare ca merge si cu valoare negativa, face sa se intrepatrunda cu elementul anterior si poate crea niste efecte interesante, care lipseste doua elemente etc - in dpg 1.13 merge, pentru versiuni mai tarzii nu mai stiu...
        :param height: Înălțimea spatiatorului - se pare ca merge si cu valoare negativa, face sa se intrepatrunda cu elementul anterior si poate crea niste efecte interesante, care lipseste doua elemente etc - in dpg 1.13 merge, pentru versiuni mai tarzii nu mai stiu...
        :param pos: tuplu sau lista de 2 elemente, cu x si y, pozitia relativa la radacina (le fereastra OS-ului, a aplicatiei), implicit 0,0, coltul stanga-sus
        :param explicit_parent: Containerul părinte în care se va plasa spatiatorul.
        """
        params_ = {
            "width": width,
            "height": height
        }
        if pos is not None:
            params_['pos'] = pos # nu stiu foarte bine daca e practica buna cu acest pos, dar sa-l lasam fiindca api-ul dpg il suporta ('dangling space', oriunde vrei, in 'spatiu' :)...)

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_spacer(**params_)

        return EasyDPGWrapperSpacer(tag=element_id)

class EasyDPGWrapperHorizontalSpacer(EasyDPGWrapper, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperVisibility):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ["mvspacer"])

    @staticmethod
    def build(width=100, explicit_parent: AnyParent = None) -> 'EasyDPGWrapperHorizontalSpacer':
        """
        Crează un spatiator orizontal cu parametrii esențiali.
        :param explicit_parent: Containerul părinte în care se va plasa spatiatorul.
        :param width: Lățimea spatiatorului - se pare ca merge si cu valoare negativa, face sa se intrepatrunda cu elementul anterior si poate crea niste efecte interesante, care lipseste doua elemente etc - in dpg 1.13 merge, pentru versiuni mai tarzii nu mai stiu...
        """
        params_ = {
            "width": width
        }
        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_spacer(**params_)

        return EasyDPGWrapperHorizontalSpacer(tag=element_id)

class EasyDPGWrapperVerticalSpacer(EasyDPGWrapper, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperVisibility):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)

        _guard_incompatible_type(self.tag(), ["mvspacer"])

    @staticmethod
    def build(height=100, explicit_parent: AnyParent = None) -> 'EasyDPGWrapperVerticalSpacer':
        """
        Crează un spatiator vertical cu parametrii esențiali.
        :param explicit_parent: Containerul părinte în care se va plasa spatiatorul.
        :param height: Inaltimea spatiatorului - se pare ca merge si cu valoare negativa, face sa se intrepatrunda cu elementul anterior si poate crea niste efecte interesante, care lipseste doua elemente etc - in dpg 1.13 merge, pentru versiuni mai tarzii nu mai stiu...
        """
        params_ = {
            "height": height
        }
        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_spacer(**params_)

        return EasyDPGWrapperVerticalSpacer(tag=element_id)

class EasyDPGWrapperButton(EasyDPGWrapper, _EasyDPGWrapperFullGeometryController, _EasyDPGWrapperVisibility, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperFullGeometryController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_button_theme)

        _guard_incompatible_type(self.tag(), ["mvbutton"])

    def set_press_callback(self, callback: lambda tag, app_data, user_data: None):
        dpg.configure_item(self.tag_, callback=callback); return self

    def set_text(self, text: str):
        dpg.configure_item(self.tag_, label=text); return self

    @staticmethod
    def build(label, width:Union[int, None]=None, height:Union[int, None]=None, background_color_hue_or_rgb: UniversalColor = None, tooltip=None, explicit_parent: AnyParent=None) -> 'EasyDPGWrapperButton':
        """
        Crează un buton simplificat cu parametrii esențiali.
        :param label: Textul de pe buton.
        :param explicit_parent: Containerul părinte în care se va plasa butonul.
        :param width: Lățimea butonului.
        :param height: Înălțimea butonului.
        :param tooltip: Tooltip-ul care va fi afișat la survolarea butonului.
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """
        params_ = {
            "label": label
        }
        if width is not None:
            params_['width'] = width
        if height is not None:
            params_['height_'] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_button(**params_)
        if tooltip:
            dpg.set_item_tooltip(element_id, tooltip)

        ref_ = EasyDPGWrapperButton(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb)
        return ref_

class EasyDPGWrapperTree(EasyDPGWrapper, _EasyDPGWrapperVisibility, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_button_theme)

        _guard_incompatible_type(self.tag(), ["mvtree"])

    def set_press_callback(self, callback: lambda tag, app_data, user_data: None):
        dpg.configure_item(self.tag_, callback=callback); return self

    def set_text(self, text: str):
        dpg.configure_item(self.tag_, label=text); return self

    @staticmethod
    def build(label, explicit_parent: AnyParent=None) -> 'EasyDPGWrapperButton':
        """
        Crează un buton simplificat cu parametrii esențiali.
        :param label: Textul de pe buton.
        :param explicit_parent: Containerul părinte în care se va plasa butonul.
        :param width: Lățimea butonului.
        :param height: Înălțimea butonului.
        :param tooltip: Tooltip-ul care va fi afișat la survolarea butonului.
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """
        params_ = {
            "label": label
        }
        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_tree_node(**params_)

        ref_ = EasyDPGWrapperTree(tag=element_id)
        return ref_

class EasyDPGWrapperInputText(EasyDPGWrapper, _EasyDPGWrapperPositionController, _EasyDPGWrapperVisibility, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperPositionController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_button_theme)

        _guard_incompatible_type(self.tag(), ["mvinputtext"])

    @staticmethod
    def build(label="", default_value: str="", explicit_parent: AnyParent=None, width=None, height=None, background_color_hue_or_rgb: UniversalColor = None, multiline: bool=False, placeholder:str = "") -> 'EasyDPGWrapperInputText':
        """
        Crează un input-text (cu cateva variante - camp pentru furnizat valori) simplificat cu parametrii esențiali.
        :param label: Textul asociat cu inputul (apare in stanga lui).
        :param explicit_parent: Containerul părinte în care se va plasa inputul.
        :param default_value: valorea implicita cu care se va crea inputul
        :param placeholder: valoare de instructiune care apare cand campul de intrare e gol
        :param multiline: daca e True, inputul va face wrap (segmentare) de text pe mai multe randuri (cred (@TODO) ca in functie de height)
        :param width: Lățimea inputului.
        :param height: Înălțimea inputului.
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """
        params_ = {
            "label": label,
            "default_value": default_value,
            "multiline": multiline,
            "hint": placeholder
        }
        if width is not None:
            params_["width"] = width
        if height is not None:
            params_["height"] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_input_text(**params_)

        ref_ = EasyDPGWrapperInputText(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb)
        return ref_

class EasyDPGWrapperInputPassword(EasyDPGWrapper, _EasyDPGWrapperPositionController, _EasyDPGWrapperVisibility, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperPositionController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_button_theme)

        _guard_incompatible_type(self.tag(), ["mvinputtext"])#, "mvinputfloat", "mvinputint", "mvinputintmulti", "mvinputfloatmulti", "mvinputdouble", "mvinputDoublemulti"])

    @staticmethod
    def build(label="", default_value: str="", explicit_parent: AnyParent=None, width=None, height=None, background_color_hue_or_rgb: UniversalColor = None) -> 'EasyDPGWrapperInputPassword':
        """
        Crează un input-parola simplificat cu parametrii esențiali.
        :param label: Textul asociat cu inputul (apare in stanga lui).
        :param explicit_parent: Containerul părinte în care se va plasa inputul.
        :param default_value: valorea implicita cu care se va crea inputul
        :param width: Lățimea inputului.
        :param height: Înălțimea inputului.
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """
        params_ = {
            "label": label,
            "default_value": default_value,
            "multiline": False,
            "password": True
        }
        if width is not None:
            params_["width"] = width
        if height is not None:
            params_["height"] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_input_text(**params_)

        ref_ = EasyDPGWrapperInputPassword(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb)
        return ref_

class EasyDPGWrapperInputInt(EasyDPGWrapper, _EasyDPGWrapperPositionController, _EasyDPGWrapperVisibility, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        _EasyDPGWrapperPositionController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_button_theme)

        _guard_incompatible_type(self.tag(), ["mvinputint"])#, "mvinputfloat", "mvinputtext", "mvinputintmulti", "mvinputfloatmulti", "mvinputdouble", "mvinputDoublemulti"])

    @staticmethod
    def build(label="", default_value: str="", explicit_parent: AnyParent=None, width=None, height=None, background_color_hue_or_rgb: UniversalColor = None, min_value: int = 0, max_value: int = 10000000, filter_manual_input_for_min: bool = True, filter_manual_input_for_max: bool = True, step: Union[int, None] = 1, ctrl_step: Union[int, None] = 2) -> 'EasyDPGWrapperInputInt':
        """
        Crează un input (cu variante - camp pentru furnizat valori) simplificat cu parametrii esențiali.
        :param label: Textul asociat cu inputul (apare in stanga lui).
        :param explicit_parent: Containerul părinte în care se va plasa inputul.
        :param default_value: valorea implicita cu care se va crea inputul
        :param min_value: valoarea minima sub care inputul nu mai coboara
        :param max_value: valoarea maxima peste care inputul nu mai urca
        :param filter_manual_input_for_min: daca e False, editarea manuala a inputului se va putea duce oricat sub min_value, altfel va fi limitata
        :param filter_manual_input_for_max: daca e False, editarea manuala a inputului se va putea duce oricat peste max_value, altfel va fi limitata
        :param step: incrementul normal (cand apesi pe butoanele +/-); None inseamna sa fie dezactivat
        :param ctrl_step: incrementul mai mare care se activeaza daca apesi tasta control, impreuna cu butoanele +/-; None inseamna sa fie dezactivat
        :param width: Lățimea inputului.
        :param height: Înălțimea inputului.
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """
        params_ = {
            "label": label,
            "default_value": default_value,
            "min_value": min_value,
            "max_value": max_value,
            "min_clamped": filter_manual_input_for_min,
            "max_clamped": filter_manual_input_for_max,
            "step": step,
            "step_fast": ctrl_step
        }
        if width is not None:
            params_["width"] = width
        if height is not None:
            params_["height"] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_input_int(**params_)

        ref_ = EasyDPGWrapperInputInt(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb)
        return ref_


class EasyDPGWrapperProgressBar(EasyDPGWrapper, _EasyDPGWrapperSizeController, _EasyDPGWrapperVisibility, _EasyDPGWrapperColor):

    def __init__(self, tag):
        EasyDPGWrapper.__init__(self, tag)
        #_EasyDPGWrapperSingleValueController.__init__(self, tag)
        _EasyDPGWrapperSizeController.__init__(self, tag)
        _EasyDPGWrapperVisibility.__init__(self, tag)
        _EasyDPGWrapperColor.__init__(self, tag, create_progressbar_theme)

        _guard_incompatible_type(self.tag(), ["mvprogressbar"])

        udata_ = dpg.get_item_user_data(tag)
        self.clbk_ = udata_['progress_callback'] if 'progress_callback' in udata_ else lambda progress: progress

    def progress(self): return dpg.get_item_user_data(self.tag_)['progress_value']
    def update_progress(self, value01):
        dpg.set_value(self.tag_, value01)
        dpg.configure_item(self.tag_, overlay=self.clbk_(value01))
        return self
    def set_progress(self, value01): return self.update_progress(value01)

    @staticmethod
    def build(overlay_callback: lambda progress: progress, explicit_parent: AnyParent=None, width=None, height=None, background_color_hue_or_rgb: UniversalColor = None) -> 'EasyDPGWrapperProgressBar':
        """
        Crează o bara de progres, simplificata, cu parametrii esențiali.
        :param overlay_callback: un lambda care proceseaza fiecare valoare a progresului si determina ce sa se afiseze, efectiv, pe bara de progres (o functie de transformare a valorii afisate a progresului)
        :param explicit_parent: Containerul părinte în care se va plasa bara de progres.
        :param width: Lățimea barii de progres.
        :param height: Înălțimea barii de progres.
        :param background_color_hue: o valoare hue (registru HSV) de la 0..7, numar fractionar; va seta culoarea butonului de baza la o culoare reprezentativa, iar pentru hover/disabled/clicked va construi automat culori vecine cu aceasta; None inseamna implicit (un gri cam intunecat un pic)
        """
        params_ = {
        }
        if width is not None:
            params_["width"] = width
        if height is not None:
            params_["height"] = height

        params_ = _try_inject_explicit_parent(explicit_parent, params_)

        element_id = dpg.add_progress_bar(**params_)

        dpg.set_item_user_data(element_id, {
            "progress_callback": overlay_callback
        })
        ref_ = EasyDPGWrapperProgressBar(tag=element_id)
        ref_.set_background_color(background_color_hue_or_rgb)
        ref_.set_progress(0.25)
        return ref_


class _EasyDPGLayoutManagerBase:

    def __init__(self, tag):
        self.tag_ = tag
        self.layout_manager_ctrl_:_LayoutManagerController = FACTORY(_LayoutManagerController)
        self.layout_manager_ctrl_._register_lm(self)

    def __del__(self):
        self.layout_manager_ctrl_._deregister_lm(self)

    def tag(self): return self.tag_

    def recalculate(self):
        raise Exception("not implemented")

    # @TODO in mod normal, functia de mai jos nu ar trebui sa primeasca regula incat sa o parseze el, ci parametrii in dictionar, care sa specifice cele necesare calculului proportional, urmand ca regula (structura ei) sa fie definita si analizat-extractata (parsed) de apelant, caci asa se poate crea si o metoda de validare specifica etc... deocamdata lasam asa, dar mai corect ar fi cum am spus
    @staticmethod
    def compute_proportional_adjuster_parts(container_tag: Union[str, int], adjust_rule: str,
                                            total_dim_in_container: int, alter_dim_total: int,
                                            result_row_provider: LMProportionalAdjusterResultRowProvider,
                                            adjuster_class_name: str = "EasyDPGWrapperProportionalVerticalAdjuster"):

        dpg_sub_elements_ = dpg.get_item_children(container_tag, 1)  # Index 1 pentru copii obișnuiți; index 0 pentru "slotul de început" ???!
        child_count_ = len(dpg_sub_elements_)
        if child_count_ <= 0:
            return {} # no descendents (children elements) so no adjusting to do

        if adjust_rule is None or len(adjust_rule) <= 0:
            perc_ = int(100.0 / child_count_)
            adjust_rule = f"{perc_}%," * child_count_
            adjust_rule = adjust_rule[:-1]
            print(
                f"WARNING: {adjuster_class_name}: provided empty rule, defaulted it with equal virtual spaces between child elements, so {perc_} % for each of them")

        # pasul 1 - determinare total unitati
        total_units_ = None
        if '%' in adjust_rule:
            total_units_ = 100
        else:
            if ':' in adjust_rule:
                try:
                    total_units_ = int(adjust_rule.split(':')[0].strip())
                except:
                    raise Exception(
                        f"ERROR: {adjuster_class_name}: recalculate: total units wrongly specified, expecting a number (followed by the : delimiter) as an adjust rule prefix, but rule seems to be broken: {adjust_rule}")
        if total_units_ is None:
            print(
                f"WARNING: {adjuster_class_name}: recalculate: total units missing, not specified: please use % in the rule parts to induce an implicit 100 as the total units or use an explicit <total_units:<rule parts> syntax for an explicit specification; current incomplete specified rule: {adjust_rule}. For now, we will default total units to 100 (so unit=percent). Adjust rule (for localisation and fixing): {adjust_rule}")
            total_units_ = 100

        # pasul 2 - extragere "parti"...
        parts_fullchunk_raw_ = adjust_rule.split(":")[1] if ":" in adjust_rule else adjust_rule
        temp_ = [p.strip().lower() for p in re.split(r'[;,]', parts_fullchunk_raw_)]
        p_ = 0
        # 'parsare' mai specifica, fiindca si extra argumentele au delimitator , sau ; si atunci nu pot folosi un simplu split, trebuie sa tin cotn si de expresiile dintre [ .. ]
        parts_raw_ = []
        while p_ < len(temp_):
            chunk_ = temp_[p_]
            if "[" in temp_[p_] and "]" not in temp_[p_]:
                while "]" not in temp_[p_]:
                    p_ += 1
                    if "[" in temp_[p_] or p_ >= len(temp_):
                        raise Exception(f"ERROR: {adjuster_class_name}: recalculate: syntax invalid adjust rule, regarding extra-args specification, see [ and ] symbols to not be missing or not being too many: {adjust_rule}")
                    chunk_ += ',' + temp_[p_]
            parts_raw_.append(chunk_)
            p_ += 1

        # 2.1. extragere extra argumente
        extra_args_ = {}
        parts_ = []
        i = 0
        for p in parts_raw_:
            if '[' in p:
                c_part_ = p[:p.find('[')]
                parts_.append(c_part_)
                args_raw_ = p[p.find('[') + 1: p.rfind(']')]
                expr_list_raw_ = [p.strip().lower() for p in re.split(r'[;,]', args_raw_)]
                extra_args_[i] = {}
                for e in expr_list_raw_:
                    arg_name_, argv_val_ = [c.strip() for c in e.split('=')]
                    if arg_name_ in ['min', 'max']:
                        argv_val_ = int(argv_val_)
                    extra_args_[i][arg_name_] = argv_val_

                    if 'u' not in c_part_ and '%' not in c_part_ and arg_name_ in ["min", "max"]: # R-urile nu au voie la min-max @ TODO asta se poate folosi si la validatorul de reguli - cum am spus, in fine, fiecare LM ar trebui sa parseze singur regula si aici sa-mi dea direct doar parametrii clari, dar e ideal ce spun, merge si asa, logica comuna la doua LM-uri...-, in fine...
                        raise Exception(f"ERROR: {adjuster_class_name}: 'max' and 'min' extra-arg cannot reside in an R part (only in parts - not in subparts- allowed); for localisation purposes, the whole rule is {adjust_rule}")

            else:
                extra_args_[i] = {}
                parts_.append(p)
            i += 1

        # 2.2. o mica validare...
        if len(parts_) != child_count_:
            raise Exception(
                f"ERROR: {adjuster_class_name}: you provided an incomplete/confussing rule as the specified rule part-count ({len(parts_)}) is not the same number as the current child count ({child_count_}): {adjust_rule}")

        # pasul 3 - calcul numar unitati
        num_units_ = sum(extract_int_scalar(p, throw_exception=True, reject_float=True) if 'u' in p or '%' in p else 0 for p in parts_)
        if num_units_ > total_units_:
            raise Exception(f"ERROR: {adjuster_class_name}: sum of all non-R part units ({num_units_}) are exceeding total units ({total_units_}). For localisation purposes, here is the whole adjust rule: {adjust_rule}")

        # pasul 4 - calcul numar subunitati (unitati-"remaining")
        num_r_units_ = sum(extract_int_scalar(p, throw_exception=True, reject_float=True) if 'r' in p else 0 for p in parts_)

        # pasul 5, calcul valori absolute per unitati (subunitatile (R-urile) se amana fiindca vedem daca unitatile raman asa sau trebuie modificate pentru constrangeri)
        unit_mu_ = total_dim_in_container / total_units_  # mu=measurement-unit

        # 5.1. calculam, de sondaj, doar partile non-R..., dar aplicam si min-max-urile...
        final_dims_per_part_ = {}
        remaining_dim_ = total_dim_in_container
        for part_idx_ in range(child_count_):
            c_part_ = parts_[part_idx_]
            if 'u' not in c_part_ and '%' not in c_part_:
                continue
            scalar_ = extract_int_scalar(c_part_, throw_exception=True, reject_float=True)
            new_dim_ = int(scalar_ * unit_mu_)
            new_dim_ = min(extra_args_[part_idx_]['max'] if 'max' in extra_args_[part_idx_] else 1000000,
                           max(extra_args_[part_idx_]['min'] if 'min' in extra_args_[part_idx_] else 0, new_dim_))
            final_dims_per_part_[part_idx_] = new_dim_
            remaining_dim_ -= new_dim_

        # -pasul 6- pana acum avem toate dimensiunile (obligatorii -care au min specificat-) calculate dupa potentialul spatiu pe care il doresc
        # verificam daca mai e loc de R-uri (cele mai joase ca prioritate), si daca da, le calculam si pe astea, daca nu, le ignoram complet (nu vor aparea pe ecran, "ghinion"...)
        if remaining_dim_ > 0:
            if num_r_units_:
                subunit_mu_ = remaining_dim_ / num_r_units_ if num_r_units_ > 0 else 0
                optional_subparts_ = [[i, subunit_mu_ * extract_int_scalar(parts_[i], throw_exception=True, reject_float=True)] for i in
                                      range(child_count_) if
                                      i not in final_dims_per_part_.keys()]
                for s in optional_subparts_:
                    final_dims_per_part_[s[0]] = s[1]
                    remaining_dim_ -= s[1]

        elif remaining_dim_ < 0 and num_r_units_ > 0:
            default_r_units_ = [parts_[i] for i in range(child_count_) if i not in final_dims_per_part_.keys()]
            if len(default_r_units_) > 0:
                print(f"WARNING: {adjuster_class_name}: R parts were excluded because of no space left: {default_r_units_}")

        # -pasul 7 - penultimul pas: micsoram proportional toate partile deja calculate, ca sa incapa in total_dim_in_container_
        if remaining_dim_ < 0:
            print(
                f"WARNING: {adjuster_class_name}: after computing mandatory and optionaly parts, we exceeded the total container dimension by {-remaining_dim_} (total dimension is {total_dim_in_container}). We will shrink all parts proportionally to fit into that space !")
            dim_ = sum([part_dim_ for part_dim_ in final_dims_per_part_.values()])
            subunitar_factor_ = total_dim_in_container / dim_
            tmp_ = {}
            for p_idx in final_dims_per_part_.keys():
                tmp_[p_idx] = int(final_dims_per_part_[p_idx] * subunitar_factor_)
            final_dims_per_part_ = tmp_

        # -pasul 8 - ultimul pas, returnam rezultatele finale
        increm_pos_ = 0
        results = {}
        final_dims_per_part_ = sorted(map(lambda part_idx: [part_idx, final_dims_per_part_[part_idx]], final_dims_per_part_.keys()), key=lambda o: o[0])
        for part_raw__ in final_dims_per_part_:
            part_idx_ = part_raw__[0]
            new_dim_ = part_raw__[1]
            se_tag = dpg_sub_elements_[part_idx_]
            results[se_tag] = result_row_provider(new_dim_, alter_dim_total, increm_pos_)
            increm_pos_ += new_dim_

        return results

class EasyDPGProportionalVerticalAdjuster(_EasyDPGLayoutManagerBase, EasyDPGWrapperInnerPanel):
    def __init__(self, tag): # sa fie numai prin injector, pentru ca EasyDPGApp e un singleton si e dependinta dorita -> sunt multe forme de a lucra cu DI vs mai-putin-DI, o forma era sa instantiez automat EasyDPGApp prin injector, manual, mai jos la self.app_ =, si atunci nu mai era nevoie de gardarea asta si nici ideea sa construiesti asa ceva prin DI, dar e un alt motiv pentru care merg pe modelul asta (iarasi, unul din mai multe cu care se putea merge): ** i-am eliminat cuvantul Wrapper, pentru ca instanta asta va trebui sa aiba un lifetime cat aplicatia (de vreme ce are chestii de ajustare continua, dupa niste reguli, etc), deci NU e wrapper, si daca nu e wrapper, nu e ceva ce ai nevoie sa-l instantiezi direct, deci o poti face prin metoda statica .build(...) (care foloseste di), deci pot folosi "oficial" (in lista de parametrii ai constructorului) DI si asta e logica de convenienta acum, pentru ca e o convenienta sa doar pun o dependinta in constructor si ea sa-mi fie furnizata "magic" (nu foarte magic, dar aproape magic, ca e vorba de folosirea injectorului :) )
        _EasyDPGLayoutManagerBase.__init__(self, tag)
        EasyDPGWrapperInnerPanel.__init__(self, tag)

        self.app_: EasyDPGApp = FACTORY(EasyDPGApp)
        self.adjust_rule_ = ""

    def __validate_rule(self, rule):
        # @TODO...
        return True

    def set_adjust_rule(self, rule=""):
        self.adjust_rule_ = rule
        return self

    def recalculate(self) -> LMRecalculateResult:
        return _EasyDPGLayoutManagerBase.compute_proportional_adjuster_parts(adjust_rule = self.adjust_rule_,
                                                                             container_tag = self.tag_,
                                                                                total_dim_in_container = dpg.get_item_rect_size(self.tag_)[1],
                                                                                alter_dim_total = dpg.get_item_rect_size(self.tag_)[0],
                                                                                result_row_provider = lambda new_dim, alter_dim_total, increm_pos: {
                                                                                    "width": alter_dim_total,
                                                                                    "height": new_dim,
                                                                                    "pos_x": 0,
                                                                                    "pos_y": increm_pos
                                                                                },
                                                                                adjuster_class_name = "EasyDPGProportionalVerticalAdjuster")


    @staticmethod
    def build(adjust_rule="", explicit_parent: AnyParent = None) -> 'EasyDPGProportionalVerticalAdjuster':
        return EasyDPGProportionalVerticalAdjuster(tag=EasyDPGWrapperInnerPanel.build(
            background_color_hue_or_rgb_and_or_alpha=(0, 0, 0, 0), explicit_parent=explicit_parent).deactivate_border().tag()).set_adjust_rule(adjust_rule)
    # @TODO trebuie sa fortez ca orice element de sub asta sa fie infasurat intr-un innerpanel (child_window)

    @staticmethod
    def build_spacer():
        return EasyDPGWrapperHorizontalSpacer.build(width = 0)


class EasyDPGProportionalHorizontalAdjuster(_EasyDPGLayoutManagerBase, EasyDPGWrapperInnerPanel):
    def __init__(self, tag):
        _EasyDPGLayoutManagerBase.__init__(self, tag)
        EasyDPGWrapperInnerPanel.__init__(self, tag)

        self.app_ = FACTORY(EasyDPGApp)
        self.adjust_rule_ = ""

    def __validate_rule(self, rule):
        # @TODO...
        return True

    def set_adjust_rule(self, rule=""):
        self.adjust_rule_ = rule
        return self

    def recalculate(self) -> LMRecalculateResult:
        return _EasyDPGLayoutManagerBase.compute_proportional_adjuster_parts(adjust_rule = self.adjust_rule_,
                                                                        container_tag = self.tag_,
                                                                        total_dim_in_container = dpg.get_item_rect_size(self.tag_)[0],
                                                                        alter_dim_total=dpg.get_item_rect_size(self.tag_)[1],
                                                                        result_row_provider = lambda new_dim, alter_dim_total, increm_pos: {
                                                                          "width": new_dim,
                                                                          "height": alter_dim_total,
                                                                          "pos_x": increm_pos,
                                                                          "pos_y": 0
                                                                        },
                                                                        adjuster_class_name = "EasyDPGProportionalHorizontalAdjuster")

    @staticmethod
    def build(adjust_rule="", explicit_parent: AnyParent = None) -> 'EasyDPGProportionalHorizontalAdjuster':
        return EasyDPGProportionalHorizontalAdjuster(tag=EasyDPGWrapperInnerPanel.build(
            background_color_hue_or_rgb_and_or_alpha=(0, 0, 0, 0), explicit_parent=explicit_parent).deactivate_border().tag()).set_adjust_rule(adjust_rule)

    @staticmethod
    def build_spacer():
        return EasyDPGWrapperVerticalSpacer.build(height = 0) # nu e la voia intamplarii ca e spatiator vertical desi ajustor orizontal; sper ca prin height=0 sa ia inaltimea maxima de la antecesor ('parinte') si width-ul sa fie ajustat de obiectul ajustor (self)

class EasyDPGPopupBoxManager:
    @staticmethod
    def configure(max_chars_per_row = 100):
        globals()['__popupbox_max_chars_per_row'] = max_chars_per_row
                 

    @staticmethod
    def __execute():
        def _callback():
            globals()["__popupbox_box_opened"] = False
            EasyDPGPopupBoxManager.__execute()

        if "__popupbox_box_opened" not in globals():
            globals()["__popupbox_box_opened"] = False

        if not globals()["__popupbox_box_opened"] and len(globals()["__popupbox_queue"]) > 0:
            request_ = globals()["__popupbox_queue"].pop()
            globals()["__popupbox_box_opened"] = True
            if '__popupbox_max_chars_per_row' in globals():
                error_or_info_box(text=request_['msg'], is_info_box=request_['type'] == "info", callback=lambda: _callback(), max_chars_per_row=globals()['__popupbox_max_chars_per_row'])
            else:
                error_or_info_box(text=request_['msg'], is_info_box=request_['type'] == "info", callback=lambda: _callback())

    @staticmethod
    def push_info_message(msg: str, unique_id = None):
        if unique_id is None:
            unique_id = int(random.random() * 10000)
        if "__popupbox_queue" not in globals():
            globals()["__popupbox_queue"] = []
        if "__popupbox_visited" not in globals():
            globals()["__popupbox_visited"] = {}

        if unique_id in globals()["__popupbox_visited"]:
            return
        globals()["__popupbox_visited"][unique_id] = True

        globals()["__popupbox_queue"].append({
            "type": "info",
            "msg": msg,
            "id": unique_id
        })
        EasyDPGPopupBoxManager.__execute()

    @staticmethod
    def push_error_message(msg: str, unique_id = None):
        if unique_id is None:
            unique_id = int(random.random() * 10000)
        if "__popupbox_queue" not in globals():
            globals()["__popupbox_queue"] = []
        if "__popupbox_visited" not in globals():
            globals()["__popupbox_visited"] = {}

        if unique_id in globals()["__popupbox_visited"]:
            return
        globals()["__popupbox_visited"][unique_id] = True

        globals()["__popupbox_queue"].append({
            "type": "error",
            "msg": msg,
            "id": unique_id
        })
        EasyDPGPopupBoxManager.__execute()

class EasyDPGLayoutManagers:
    ProportionalVerticalAdjuster = EasyDPGProportionalVerticalAdjuster
    ProportionalHorizontalAdjuster = EasyDPGProportionalHorizontalAdjuster

class EasyDPGWrapperFactory:
    #def __init__(self):
    #    pass
    _VISIBILITY_DPG_ITEMS = ["mvbutton", "mvfiledialog", "mvtext", "mvcheckbox", "mvgroup", "mvwindowappitem",
                             "mvchildwindow", "mvspacer"]  # ,TODO...]
    @staticmethod
    def create_wrapper(tag):
        type_ = dpg.get_item_type(tag).split("::")[1].strip().lower()

        if type_ == "mvbutton":
            return EasyDPGWrapperButton(tag)
        elif type_ == "mvfiledialog":
            return EasyDPGWrapperFileDialog(tag)
        elif type_ == "mvtext":
            return EasyDPGWrapperText(tag)
        elif type_ == "mvcheckbox":
            return EasyDPGWrapperCheckbox(tag)
        elif type_ == "mvgroup":
            return EasyDPGWrapperGroup(tag)
        elif type_ == "mvwindowappitem":
            conf_ = dpg.get_item_configuration(tag)
            if "popup" in conf_ and conf_["popup"] is True:
                return EasyDPGWrapperPopup(tag)
            if "modal" in conf_ and conf_["modal"] is True:
                return EasyDPGWrapperModal(tag)
            return EasyDPGWrapperPrimaryPanel(tag)
        elif type_ == "mvchildwindow":
            return EasyDPGWrapperInnerPanel(tag)
        elif type_ == "mvspacer":
            return EasyDPGWrapperSpacer(tag)
        else:
            print(f"WARNING: EasyDPGWrapperFactory: type {type_} for dpg tag {tag} is not supported, no specific wrapper found, retuning a generic wrapper but without any additional functionalities...! @TODO This type should be implemented with specific a wrapper subclass")
            return EasyDPGWrapper(tag)

class EasyDPGWidget:

    def __init__(self, builder: BuilderCallback = lambda widget, elements_register: None, redux_store: ReduxStore = None, ui_errors_callback = lambda err, err_type: None, lookup_name: str = None):
        self.builder_ = builder
        self.redux_store_ = redux_store
        redux_store.set_uncatched_dispatched_errors_callback(ui_errors_callback)

        self.elements_registry_: ElementsRegistry = {}
        self.effects_ = {} # @TODO parametrii dinamici, pot fi oricati, dar ar fi bine sa fie documentati aici, in lista, ca sa fie vizibili, intr-o forma sau alta --> si variabil asa nu prea e corect pt evolutia codului, vedem daca ramane asa sau complicam lucrurile cu vreo structura dedicata cu formalizarea parametrilor
        self.events_ = {} # @TODO parametrii dinamici, pot fi oricati, dar ar fi bine sa fie documentati aici, in lista, ca sa fie vizibili, intr-o forma sau alta --> si variabil asa nu prea e corect pt evolutia codului, vedem daca ramane asa sau complicam lucrurile cu vreo structura dedicata cu formalizarea parametrilor
        self.event_listeners_ = {}

        self.app_: EasyDPGApp = FACTORY(EasyDPGApp)
        if lookup_name is not None:
            self.app_._auto_register_widget(self, lookup_name)

    def app(self): return self.app_

    def _dispatch_event(self, event, *args, **kwargs):
        if event not in self.event_listeners_:
            return
        for l in self.event_listeners_[event]:
            l(*args, **kwargs)

    def __clean_deleted_registered_elements(self):
        processed = True
        while processed is True:
            processed = False
            for id_ in self.elements_registry_.keys():
                e = self.elements_registry_[id_]
                if not dpg.does_item_exist(e.tag()):
                    processed = True
                    del self.elements_registry_[id_]
                    break

    def register_element(self, dpg_tag_or_wrapper: Union[EasyDPGWrapper, int, str], id):
        if isinstance(dpg_tag_or_wrapper, EasyDPGWrapper):
            self.elements_registry_[id] = dpg_tag_or_wrapper
        else:
            self.elements_registry_[id] = EasyDPGWrapperFactory.create_wrapper(dpg_tag_or_wrapper)

    def lookup_element(self, id: str):
        self.__clean_deleted_registered_elements()
        return self.elements_registry_[id] if id in self.elements_registry_ else None
    def registered_elements(self):
        self.__clean_deleted_registered_elements()
        return self.elements_registry_.copy()

    def build(self):
        self.builder_(self, self.register_element)
        return self

    def apply_effect(self, effect: str, *args, **kwargs): # efect + parametrii efect
        if effect not in self.effects_.keys():
            print(f"WARNING: EasyDPGWidget: apply_effect: Ignoring call, as effect '{effect}' doesn't exist in current widget, available effects are:\n{self.effects_.keys()}")
            return
        self.effects_[effect](*args, **kwargs)

    def listen_on_ievent(self, internal_event, callback=lambda ev, dummy_parameters: print("WARNING: EasyDPGWidget: listen_on_ievent: this is a default NOP callback and should be replaced with a specialized one, but take into account the parameters as this callback can take any parameter provided when the event is being triggered...")):
        if internal_event not in self.event_listeners_:
            self.event_listeners_[internal_event] = []
        self.event_listeners_[internal_event].append(callback)

    def effects(self): return self.effects_
    def ievents(self): return self.events_

    def listen_on_redux(self, redux_xpath, callback: WidgetReduxListener = lambda widget, registry, xpath, value: print('WARNING: EasyDPGWidget: listen_on_redux: implicit NOP callback, you should replace this with a specific one !')):
        self.redux_store_.subscribe(lambda xpath, value: callback(self, self.elements_registry_, xpath, value),  xpath=redux_xpath)


'''
if __name__ == "__main__":
    def create_ui():
        def show_type(sender, app_data, user_data):
            item_type = dpg.get_item_type(user_data)
            print(f"Tipul elementului cu tag-ul {user_data} este {item_type}.")


        #with dpg.window(label="Example Window") as ww:
        with EasyDPGWrapperPrimaryPanel.build(label="aaa", width=900, height=800, pos=[0, 0], completely_transparent=False, visible_scrollbars="") as ww:
            ww.set_background_color([70, 114, 180])
            #c = dpg.pop_container_stack()
            #print(f"current container: {c}")
            #dpg.push_container_stack(c)

            with EasyDPGWrapperGroup.build(type="h"):
                #dpg.add_checkbox("hhhhh", parent=ww)
                button_tag = dpg.add_button(label="Află tipul slider-ului")
                EasyDPGWrapperSpacer.build(width=50)
                haha = EasyDPGWrapperButton.build("Haha-a-mers")

            slider_tag = dpg.add_slider_float(label="Slider Float")

            # Asociază callback-ul cu butonul și pasează tag-ul slider-ului ca date utilizator
            dpg.set_item_user_data(button_tag, slider_tag)
            dpg.set_item_callback(button_tag, show_type)

            EasyDPGWrapperButton(button_tag).set_press_callback(lambda: print('primul buton apasat')).set_background_color([0, 255, 0])
            #sw = dpg.add_child_window(label="subcontainer", height=300)
            sw = EasyDPGWrapperInnerPanel.build(label="interior-bbb", height=200, pos=(0, 500), visible_scrollbars="").set_background_color([0, 0, 255])

        l = EasyDPGWrapperText.build("...", explicit_parent=ww)
        EasyDPGWrapperButton.build("inca un buton", explicit_parent=sw).set_text("inca unul he he he!").increase_width(2.0).increase_height(1.0).set_background_color(359)
        print(haha)
        haha.set_press_callback(lambda: EasyDPGWrapperFileDialog.build(width=400, height=300, dialog_type="file").open().set_submit_callback(lambda tag, selections: l.set_text(selections[0])))
        cb = EasyDPGWrapperCheckbox.build("un checkbox", explicit_parent=ww, default_value=True).set_submit_callback(lambda t, value: print(f'checkbox val {value}'))
        #cb.set_submit_callback(lambda t, value: print(f'checkbox val {cb.value()}'))

        #with EasyDPGWrapperModal.build("Un modal", width=1000, height=600):
        #    EasyDPGWrapperText.build("alabalaportocala")
        #    EasyDPGWrapperButton.build("Apasa aici !")

        # grup
        # culoare tema pe EasyDPGApp
        # culori pe buton si pe panou

        with EasyDPGWrapperPopup.build("Si un popup mic", width=1200, height=200):
            EasyDPGWrapperText.build("o instiintare")

        threading.Timer(3, lambda: cb.set_value(False)).start()
        threading.Timer(5, lambda: cb.set_value(True)).start()
        threading.Timer(7, lambda: cb.set_value(False)).start()

    #dpg.show_style_editor()

    app = DPGApp()
    app.start(create_ui)
'''


if __name__ == "__main__":
    from dearpygui import dearpygui as dpg
    from .redux import Action, ReduxStateRoot, logger_middleware
    from .generic_utils import overwrite_nones

    def Action_AddPost(name) -> Action: return Action("AddPost", {"name": name})
    def Action_RemoveLastPost() -> Action: return Action("RemoveLastPost", {})
    def Action_AddComment(text) -> Action: return Action("AddComment", {"text": text})
    MyState = ReduxStateRoot("MyAppState", ["posts", "comments"])
    MyState.__new__.__defaults__ = ([], [])

    @overwrite_nones({"posts": []})
    def posts_reducer(posts: List[Dict], action: Action=None) -> List[Dict]:
        if action.name == 'AddPost':
            return posts + [{"name": action.payload["name"]}]
        if action.name == 'RemoveLastPost':
            return posts[:-1]
        return posts

    @overwrite_nones({"comments": []})
    def comments_reducer(comments: List[Dict], action: Action) -> List[Dict]:
        if action.name == 'AddComment':
            return comments + [{"text": action.payload["text"]}]
        return comments

    store = ReduxStore(reducer_or_substatekey2reducer_map={
        "posts": posts_reducer,
        "comments": comments_reducer}
    , initial_state=MyState(), middlewares=[logger_middleware])

    app = create_app()

    def global_listener(path=None, state={}):
        print(f"state: {state}")

    store.subscribe(listener=global_listener)

    from uuid import uuid4

    def build(widget: EasyDPGWidget, re: RegisterElementFunc):
        '''
        # varianta veche, cu dpg nativ etc, deja sunt doua moduri de a introduce abonari la redux, una la fata locului, una pe urma...
        def update_posts(element, new_posts):
            print(f"inserted new posts, will update the ui with: {new_posts}")
            # dpg.add_text(new_posts[-1]["name"], parent="parent_w")
            dpg.delete_item(element, children_only=True)
            for post in new_posts:
                dpg.add_text(post["name"], parent=element)

        with dpg.window(label="Redux with DPG Example", tag="parent_w") as w:
            button_id = dpg.add_button(label="Append", callback=lambda: store.dispatch(Action_AddPost(name=f"Alabala-{str(uuid4())[:4]}")))
            button_id = dpg.add_button(label="Remove last", callback=lambda: store.dispatch(Action_RemoveLastPost()))
            counter_label_id = dpg.add_text("Counter: 0")
            #counter_label_element = GenericDPGElement(counter_label_id)
            #binding_system.bind(counter_label_element, "counter", update_counter_label)
            #post_container = dpg.add_group(tag="post_container")
            re(dpg.add_group(tag="post_container"), "POSTS_CONTAINER")
            #widget.listen_on_redux('posts', lambda widget, registry, xpath, value: update_posts(post_container, value))
            #binding_sys.bind(element=post_container, state_path="posts", update_func=update_posts)
        '''

        # varianta noua
        def update_posts(container: EasyDPGLayoutManagers.ProportionalVerticalAdjuster, new_posts):
            #print(f"inserted new posts, will update the ui with: {new_posts}")
            container.delete_children()
            for post in new_posts:
                EasyDPGWrapperText.build(post["name"], explicit_parent=container)

        with EasyDPGWrapperInnerPanel.build("Redux with DPG example"):
            EasyDPGWrapperButton.build("Append").set_press_callback(lambda: store.dispatch(Action_AddPost(name=f"Alabala-{str(uuid4())[:4]}")))
            EasyDPGWrapperButton.build("Remove last").set_press_callback(lambda: store.dispatch(Action_RemoveLastPost()))
            EasyDPGWrapperText.build("Counter: 0")
            re(EasyDPGLayoutManagers.ProportionalVerticalAdjuster.build(), "POSTS_CONTAINER")

        widget.listen_on_redux(redux_xpath="posts", callback=lambda widget, registry, xpath, value: update_posts(registry["POSTS_CONTAINER"], value))

    root_widget = EasyDPGWidget(builder=lambda widget, register_element: build(widget, register_element), redux_store=store)

    app.start(create_ui=lambda: root_widget.build())


'''
if __name__ == "__main__":
    import dearpygui.dearpygui as dpg

    # Inițializăm DearPyGui
    dpg.create_context()

    # Creăm o fereastră cu câteva elemente
    with dpg.window(label="Root Window") as w:
        print(f'root: {w}')
        with dpg.group() as g:
            print(f'group1: {g}')
            print(f'button1: {dpg.add_button(label="Button 1", tag="button1")}')
            print(f'button2: {dpg.add_button(label="Button 2", tag="button2")}')
        print(f'text1: {dpg.add_text("This is a text", tag="text1")}')


    # Inițializăm structurile pentru a stoca arborele și indecșii
    node_list = {}
    entry_index = {}
    exit_index = {}
    index = 0
    depths = {}

    # Funcție pentru parcurgerea în adâncime și calculul indecșilor
    def dfs(node_tag, depth = 0):
        global index
        entry_index[node_tag] = index
        depths[node_tag] = depth
        children_ = dpg.get_item_children(node_tag, 1)
        #print([dpg.get_item_configuration(child) for child in children_])
        index += 1

        for child in children_:  # Accesăm copiii itemului
            dfs(child, depth + 1)

        exit_index[node_tag] = index


    # Start DFS de la rădăcina arborelui
    dfs(w)

    # Afișăm indecșii de intrare și ieșire
    print("Entry Indexes:", entry_index)
    print("Exit Indexes:", exit_index)
    print("Depths:", depths)

    # Cleanup DPG
    dpg.destroy_context()
'''

'''
if __name__ == "__main__":
    import dearpygui.dearpygui as dpg


    def setup():
        with dpg.window(label="Fereastra Principala", width=800, height=400):
            # Primul nivel de child_window
            with dpg.child_window(label="Child Window Nivel 1"):
                dpg.add_text("Acesta este primul nivel.")

                with dpg.child_window(width=1450):
                # Al doilea nivel de child_window
                    with dpg.child_window(width=225, autosize_y=True, pos=(0, 0)):
                        dpg.add_text("Acesta este al doilea nivel !!.")

                        # Al treilea nivel de child_window
                        with dpg.child_window(label="Child Window Nivel 211", width=240, height=340):
                            dpg.add_text("Acesta este al treilea nivel.")
                            dpg.add_button(label="Buton în Nivelul 3")

                    with dpg.child_window(autosize_y=True, pos=(230, 0)):
                        dpg.add_text("*Acesta este al doilea nivel. !!!!")


    dpg.create_context()
    dpg.create_viewport(title='Exemplu de Child Windows în DPG', width=800, height=600)
    dpg.setup_dearpygui()
    setup()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()
'''
