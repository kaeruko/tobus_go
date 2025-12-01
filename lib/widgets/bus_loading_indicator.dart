import 'package:flutter/cupertino.dart';

class BusLoadingIndicator extends StatefulWidget {
  const BusLoadingIndicator({super.key});

  @override
  State<BusLoadingIndicator> createState() => _BusLoadingIndicatorState();
}

class _BusLoadingIndicatorState extends State<BusLoadingIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late final Animation<Offset> _offsetAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..repeat();

    _offsetAnimation = Tween<Offset>(
      begin: const Offset(-0.5, 0.0),
      end: const Offset(1.5, 0.0),
    ).animate(CurvedAnimation(
      parent: _controller,
      curve: Curves.linear,
    ));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        SlideTransition(
          position: _offsetAnimation,
          child: AnimatedBuilder(
            animation: _controller,
            builder: (context, child) {
               final int frame = (_controller.value * 40).floor() % 4; 
               String image;
               switch (frame) {
                 case 0: image = 'assets/images/bus_loading_01.png'; break;
                 case 1: image = 'assets/images/bus_loading_02.png'; break;
                 case 2: image = 'assets/images/bus_loading_03.png'; break;
                 case 3: image = 'assets/images/bus_loading_04.png'; break;
                 default: image = 'assets/images/bus_loading_01.png';
               }
               return SizedBox(
                 width: 80,
                 child: Image.asset(
                   image,
                   gaplessPlayback: true,
                 ),
               );
            },
          ),
        ),
        const Text('検索中...', style: TextStyle(color: CupertinoColors.inactiveGray)),
      ],
    );
  }
}
